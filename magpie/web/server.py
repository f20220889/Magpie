"""FastAPI app: serves the Magpie UI and a per-user JSON API over the orchestrator.

All ``/api`` data endpoints require an authenticated session (see
``magpie.web.auth``) and operate on a ``KnowledgeStore`` bound to that user, so
users can only ever read or modify their own data. Launch with ``magpie serve``.
"""

from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from magpie.config import settings
from magpie.knowledge.models import CardStatus
from magpie.knowledge.store import SIGNAL_WEIGHTS, KnowledgeStore
from magpie.web.auth import router as auth_router
from magpie.web.auth import require_user

UI_DIR = Path(__file__).resolve().parents[2] / "ui"

app = FastAPI(title="Magpie", docs_url="/api/docs")
app.include_router(auth_router)


# --- security headers on every response ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            # SPA + Google Fonts; no inline script. Adjust if you add CDNs.
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'",
        )
        return response


app.add_middleware(SecurityHeadersMiddleware)


def user_store(user: dict = Depends(require_user)) -> KnowledgeStore:
    """A KnowledgeStore bound to the authenticated user."""
    store = KnowledgeStore(user_id=user["id"])
    store.init_db()
    return store


# --- request models ---
class InitBody(BaseModel):
    domains: list[str] = []
    skills: dict[str, list[str]] = {}   # domain name -> skills
    known: list[str] = []


class DiscoverBody(BaseModel):
    prompt: str
    top: int = 6


class LearnBody(BaseModel):
    card_id: int | None = None
    title: str
    overview: str = ""
    source_url: str | None = None
    tags: list[str] = []


class SignalBody(BaseModel):
    card_id: int
    type: str   # thumbs_up | thumbs_down | too_basic | too_advanced | irrelevant


# --- API (all endpoints below are authenticated + user-scoped) ---
@app.get("/api/health")
def health(user: dict = Depends(require_user)) -> dict:
    from magpie.llm.base import LLMError
    from magpie.llm.factory import get_llm

    try:
        h = get_llm().health()
        return {"ok": True, **h}
    except LLMError as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/profile")
def get_profile(store: KnowledgeStore = Depends(user_store)) -> dict:
    return store.profile()


@app.get("/api/learned")
def get_learned(store: KnowledgeStore = Depends(user_store)) -> dict:
    return {"learned": [t.model_dump(mode="json") for t in store.list_learned()]}


@app.post("/api/init")
def post_init(body: InitBody, store: KnowledgeStore = Depends(user_store)) -> dict:
    ids: dict[str, int] = {}
    for d in body.domains:
        ids[d] = store.add_domain(d)
    for domain, skills in body.skills.items():
        if domain in ids:
            for s in skills:
                store.add_skill(ids[domain], s)
    for topic in body.known:
        store.add_learned_topic(title=topic, summary="(seeded at onboarding)")
    return store.profile()


@app.post("/api/skills/extract")
def extract_skills(
    file: UploadFile = File(...), user: dict = Depends(require_user)
) -> dict:
    """Read an uploaded resume (PDF/Word/image/text) and return suggested skills.

    Returns ``{domains: [{name, skills:[...]}]}`` for the user to verify in the
    UI; nothing is saved here. The verified result is persisted via /api/init.
    """
    from magpie.ingest.resume import IngestError, extract_skills_from_upload
    from magpie.llm.base import LLMError

    data = file.file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(data) > limit:
        raise HTTPException(
            status_code=413, detail=f"file too large (max {settings.max_upload_mb} MB)"
        )
    try:
        return extract_skills_from_upload(
            file.filename or "", file.content_type or "", data
        )
    except IngestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@app.post("/api/discover")
def post_discover(body: DiscoverBody, user: dict = Depends(require_user)) -> dict:
    from magpie.agent.orchestrator import Orchestrator

    store = KnowledgeStore(user_id=user["id"])
    store.init_db()
    cards = Orchestrator(store=store).run(body.prompt)[: body.top]
    return {"cards": [c.model_dump(mode="json") for c in cards]}


@app.get("/api/suggestions")
def get_suggestions(n: int = 5, store: KnowledgeStore = Depends(user_store)) -> dict:
    from magpie.agent.adjacency import AdjacencySuggester
    from magpie.llm.base import LLMError

    try:
        items = AdjacencySuggester().suggest(store.profile(), store.learned_titles(), n)
    except LLMError as e:
        # LLM unreachable/misconfigured -> a clean 503 the UI can show, not a 500.
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"suggestions": items}


@app.get("/api/roadmap")
def get_roadmap(n: int = 6, store: KnowledgeStore = Depends(user_store)) -> dict:
    from magpie.agent.roadmap import RoadmapBuilder
    from magpie.llm.base import LLMError

    try:
        steps = RoadmapBuilder().build(store.profile(), store.learned_titles(), n)
    except LLMError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"roadmap": steps}


@app.get("/api/export")
def export_hoard(
    format: str = "md", store: KnowledgeStore = Depends(user_store)
) -> Response:
    from magpie import exporter

    if format not in exporter.FORMATS:
        raise HTTPException(status_code=400, detail=f"unknown format: {format}")
    topics = [t.model_dump(mode="json") for t in store.list_learned(limit=10000)]
    content = exporter.export(topics, format)
    filename = f"magpie-hoard.{exporter.EXT[format]}"
    return Response(
        content,
        media_type=exporter.MIME[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/history")
def get_history(store: KnowledgeStore = Depends(user_store)) -> dict:
    return {"runs": store.list_runs()}


@app.get("/api/run/{run_id}")
def get_run(run_id: int, store: KnowledgeStore = Depends(user_store)) -> dict:
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="not found")
    return {
        "run": run,
        "cards": [c.model_dump(mode="json") for c in store.get_run_cards(run_id)],
    }


@app.delete("/api/learned/{topic_id}")
def delete_learned(topic_id: int, store: KnowledgeStore = Depends(user_store)) -> dict:
    return {"ok": store.forget_topic(topic_id)}


@app.delete("/api/run/{run_id}")
def delete_run(run_id: int, store: KnowledgeStore = Depends(user_store)) -> dict:
    return {"ok": store.delete_run(run_id)}


@app.get("/api/discover/stream")
def discover_stream(
    prompt: str, top: int = 6, user: dict = Depends(require_user)
) -> StreamingResponse:
    """Run a discovery and stream progress as Server-Sent Events.

    The session cookie is sent automatically by EventSource (same-origin), so
    this stays scoped to the authenticated user.
    """
    from magpie.agent.orchestrator import Orchestrator

    store = KnowledgeStore(user_id=user["id"])
    store.init_db()
    events: queue.Queue = queue.Queue()
    _SENTINEL = object()

    def on_progress(stage: str, message: str) -> None:
        events.put(("progress", {"stage": stage, "message": message}))

    def worker() -> None:
        try:
            cards = Orchestrator(store=store).run(prompt, progress=on_progress)[:top]
            events.put(("done", {"cards": [c.model_dump(mode="json") for c in cards]}))
        except Exception as e:  # surface a clean message to the UI
            events.put(("error", {"message": str(e)}))
        finally:
            events.put(_SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            item = events.get()
            if item is _SENTINEL:
                break
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/learn")
def post_learn(body: LearnBody, store: KnowledgeStore = Depends(user_store)) -> dict:
    store.add_learned_topic(
        title=body.title, summary=body.overview,
        source_url=body.source_url, tags=body.tags,
    )
    if body.card_id is not None:
        # Ownership is enforced in the store; a foreign card raises and 500s,
        # but the card id always comes from the user's own run in practice.
        store.set_card_status(body.card_id, CardStatus.learned)
        store.add_signal(body.card_id, "learned")
    return {"ok": True}


@app.post("/api/signal")
def post_signal(body: SignalBody, store: KnowledgeStore = Depends(user_store)) -> dict:
    if body.type not in SIGNAL_WEIGHTS:
        raise HTTPException(status_code=400, detail=f"unknown signal type: {body.type}")
    store.add_signal(body.card_id, body.type)
    return {"ok": True}


# --- static UI ---
@app.get("/")
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")


if UI_DIR.exists():
    # Static assets (css/js/images) are public so the login screen can render;
    # all data lives behind the authenticated /api endpoints above.
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
