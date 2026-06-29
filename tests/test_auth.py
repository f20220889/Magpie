"""Auth + per-user isolation (IDOR) tests via the FastAPI TestClient.

These prove the two things the multi-user feature must guarantee:
  1. data endpoints reject unauthenticated requests, and
  2. one user can never read or mutate another user's data, even by guessing ids.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from magpie.config import settings
from magpie.web.server import app


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point every store at a throwaway DB for the duration of a test."""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "auth.db"))


@pytest.fixture(autouse=True)
def _reset_limits():
    """Clear the per-IP throttles so tests don't bleed attempts into each other."""
    from magpie.web import auth

    auth._login_limiter._hits.clear()
    auth._signup_limiter._hits.clear()
    yield


def _client() -> TestClient:
    return TestClient(app)


def _signup(client: TestClient, email: str, password: str = "password123") -> dict:
    r = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def test_signup_login_logout_flow(db):
    c = _client()
    user = _signup(c, "alice@example.com")
    assert user["email"] == "alice@example.com"
    assert "password_hash" not in user and "google_sub" not in user  # never leaked
    assert c.get("/api/auth/me").status_code == 200

    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401

    # Log back in with the same credentials.
    r = c.post("/api/auth/login",
               json={"email": "alice@example.com", "password": "password123"})
    assert r.status_code == 200
    assert c.get("/api/auth/me").status_code == 200


def test_unauthenticated_endpoints_rejected(db):
    c = _client()
    for path in ("/api/profile", "/api/learned", "/api/history", "/api/suggestions"):
        assert c.get(path).status_code == 401, path


def test_duplicate_email_rejected(db):
    c = _client()
    _signup(c, "dup@example.com")
    r = _client().post("/api/auth/signup",
                       json={"email": "dup@example.com", "password": "password123"})
    assert r.status_code == 409


def test_short_password_rejected(db):
    r = _client().post("/api/auth/signup",
                       json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 400


def test_login_errors_are_generic(db):
    """Unknown email and wrong password return the *same* message (no enumeration)."""
    c = _client()
    _signup(c, "bob@example.com")
    c.post("/api/auth/logout")
    wrong = c.post("/api/auth/login",
                   json={"email": "bob@example.com", "password": "wrongpass1"})
    unknown = c.post("/api/auth/login",
                     json={"email": "ghost@example.com", "password": "wrongpass1"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_login_is_rate_limited(db):
    c = _client()
    _signup(c, "rl@example.com")
    c.post("/api/auth/logout")
    codes = [
        c.post("/api/auth/login",
               json={"email": "rl@example.com", "password": "nope12345"}).status_code
        for _ in range(15)
    ]
    assert 429 in codes  # brute force eventually throttled


def _fake_google(monkeypatch, *, email_verified: bool):
    """Stub Google's token + userinfo HTTP calls for the OAuth callback."""
    from magpie.web import auth

    monkeypatch.setattr(auth.settings, "google_client_id", "cid")
    monkeypatch.setattr(auth.settings, "google_client_secret", "secret")

    class _R:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: _R({"access_token": "tok"}))
    monkeypatch.setattr(
        auth.httpx, "get",
        lambda *a, **k: _R({
            "sub": "google-123", "email": "victim@example.com",
            "email_verified": email_verified, "name": "V",
        }),
    )


def test_google_unverified_email_rejected_no_account(db, monkeypatch):
    """An unverified Google email must NOT create or link an account (leak guard)."""
    from magpie.web import auth

    _fake_google(monkeypatch, email_verified=False)
    c = _client()
    c.cookies.set("magpie_oauth_state", "st8")
    r = c.get("/api/auth/google/callback?code=abc&state=st8", follow_redirects=False)
    assert r.status_code == 403
    assert auth.base_store().get_user_by_email("victim@example.com") is None


def test_google_verified_email_logs_in(db, monkeypatch):
    from magpie.web import auth

    _fake_google(monkeypatch, email_verified=True)
    c = _client()
    c.cookies.set("magpie_oauth_state", "st8")
    r = c.get("/api/auth/google/callback?code=abc&state=st8", follow_redirects=False)
    assert r.status_code == 303  # redirect into the app
    assert auth.base_store().get_user_by_email("victim@example.com") is not None


def test_idor_users_are_isolated(db):
    # Alice creates a profile + a learned topic.
    alice = _client()
    _signup(alice, "alice@example.com")
    alice.post("/api/init", json={
        "domains": ["Backend"], "skills": {"Backend": ["Python"]}, "known": ["REST"],
    })
    alice.post("/api/learn", json={"title": "Alice secret topic", "overview": "x"})
    alice_topics = alice.get("/api/learned").json()["learned"]
    topic_id = alice_topics[0]["id"]
    assert any(t["title"] == "Alice secret topic" for t in alice_topics)

    # Bob is a separate session and must see none of Alice's data.
    bob = _client()
    _signup(bob, "bob@example.com")
    assert bob.get("/api/learned").json()["learned"] == []
    assert bob.get("/api/profile").json()["domains"] == []

    # Bob cannot read Alice's run by guessing ids…
    runs = alice.get("/api/history").json()["runs"]
    if runs:
        rid = runs[0]["id"]
        assert bob.get(f"/api/run/{rid}").status_code == 404

    # …and cannot delete Alice's learned topic.
    assert bob.delete(f"/api/learned/{topic_id}").json()["ok"] is False
    still = alice.get("/api/learned").json()["learned"]
    assert any(t["id"] == topic_id for t in still)  # untouched
