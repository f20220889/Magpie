"""Authentication: email/password + Google OAuth, with secure sessions.

Sessions are server-side: a random token is stored in the ``session`` table and
sent to the browser as an HttpOnly, SameSite=Lax cookie (Secure in production).
The ``require_user`` dependency resolves the cookie to a user and is attached to
every data endpoint, so unauthenticated requests are rejected and each request
is scoped to its own user.
"""

from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

from magpie.config import settings
from magpie.knowledge.store import KnowledgeStore
from magpie.security import hash_password, new_token, verify_password
from magpie.web.ratelimit import RateLimiter, client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_OAUTH_STATE_COOKIE = "magpie_oauth_state"

# Per-IP brute-force throttles. Login is the sensitive one; signup is capped to
# slow mass account creation.
_login_limiter = RateLimiter(max_hits=10, window_seconds=300)    # 10 / 5 min
_signup_limiter = RateLimiter(max_hits=8, window_seconds=3600)   # 8 / hour


def base_store() -> KnowledgeStore:
    """An unbound store for user/session management."""
    store = KnowledgeStore()
    store.init_db()
    return store


# --- request models ---
class SignupBody(BaseModel):
    email: str
    password: str
    display_name: str = ""

    @field_validator("email")
    @classmethod
    def _valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("invalid email address")
        return v


class LoginBody(BaseModel):
    email: str
    password: str


# --- cookie helpers ---
def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie,
        value=token,
        max_age=settings.session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(settings.session_cookie, path="/")


def _start_session(store: KnowledgeStore, user_id: int, response: Response) -> None:
    token = new_token()
    store.create_session(user_id, token, settings.session_days)
    _set_session_cookie(response, token)


def _public_user(user: dict) -> dict:
    """Never leak password_hash / google_sub to the client."""
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user.get("display_name", ""),
    }


# --- dependency: the authenticated user ---
def require_user(request: Request) -> dict:
    token = request.cookies.get(settings.session_cookie, "")
    user = base_store().session_user(token)
    if not user:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


# --- endpoints ---
@router.get("/config")
def auth_config() -> dict:
    return {"google_enabled": settings.google_enabled}


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    return _public_user(user)


@router.post("/signup")
def signup(body: SignupBody, request: Request, response: Response) -> dict:
    _signup_limiter.check(client_ip(request))
    store = base_store()
    if store.get_user_by_email(body.email):
        raise HTTPException(status_code=409, detail="email already registered")
    try:
        pw_hash = hash_password(body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    uid = store.create_user(
        email=body.email, password_hash=pw_hash, display_name=body.display_name
    )
    _start_session(store, uid, response)
    return _public_user(store.get_user(uid))


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response) -> dict:
    _login_limiter.check(client_ip(request))
    store = base_store()
    user = store.get_user_by_email(body.email)
    # Same generic error whether the email is unknown or the password is wrong.
    if not user or not verify_password(body.password, user.get("password_hash")):
        raise HTTPException(status_code=401, detail="invalid email or password")
    _start_session(store, user["id"], response)
    return _public_user(user)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(settings.session_cookie, "")
    if token:
        base_store().delete_session(token)
    _clear_session_cookie(response)
    return {"ok": True}


# --- Google OAuth (authorization code flow) ---
_GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def _redirect_uri(request: Request) -> str:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri
    return str(request.url_for("google_callback"))


@router.get("/google/login")
def google_login(request: Request) -> RedirectResponse:
    if not settings.google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in not configured")
    state = new_token()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = httpx.URL(_GOOGLE_AUTH, params=params)
    resp = RedirectResponse(str(url))
    # State cookie defends against CSRF on the callback.
    resp.set_cookie(
        _OAUTH_STATE_COOKIE, state, max_age=600, httponly=True,
        samesite="lax", secure=settings.cookie_secure, path="/",
    )
    return resp


@router.get("/google/callback", name="google_callback")
def google_callback(request: Request, code: str = "", state: str = "") -> Response:
    if not settings.google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in not configured")
    expected = request.cookies.get(_OAUTH_STATE_COOKIE, "")
    if not state or not expected or state != expected:
        raise HTTPException(status_code=400, detail="invalid OAuth state")

    try:
        token_resp = httpx.post(
            _GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": _redirect_uri(request),
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json()["access_token"]
        info = httpx.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        info.raise_for_status()
        profile = info.json()
    except (httpx.HTTPError, KeyError, ValueError):
        raise HTTPException(status_code=502, detail="Google sign-in failed")

    sub = profile.get("sub")
    email = (profile.get("email") or "").lower()
    raw_verified = profile.get("email_verified")
    email_verified = raw_verified is True or str(raw_verified).lower() == "true"
    if not sub or not email:
        raise HTTPException(status_code=502, detail="Google account missing email")
    if not email_verified:
        # Never trust an unverified Google email: matching it to an existing
        # account would let an attacker take over that account (and its data)
        # just by owning a Google profile that claims the address.
        raise HTTPException(status_code=403, detail="Google email is not verified")

    store = base_store()
    user = store.get_user_by_google_sub(sub) or store.get_user_by_email(email)
    if user is None:
        uid = store.create_user(
            email=email, google_sub=sub, display_name=profile.get("name", "")
        )
    else:
        uid = user["id"]
        if not user.get("google_sub"):
            store.link_google_sub(uid, sub)

    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    _start_session(store, uid, resp)
    return resp
