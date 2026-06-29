"""Database-backed persistence for the knowledge base (SQLAlchemy Core).

Runs on **SQLite** (zero-setup local default) or **Postgres** (set
``DATABASE_URL`` for global deploy — survives restarts on ephemeral-disk hosts).
The same code serves both: SQLAlchemy handles dialect + parameter binding and
gives a pooled engine for concurrent web requests.

Holds users, sessions, domains, skills, learned topics, runs, topic cards, and
feedback signals. All knowledge data is scoped to a ``user_id``: a
``KnowledgeStore`` is bound to one user at construction, and every read/write is
filtered by that user. Cross-user access is therefore impossible through this
API — a request for another user's run/topic id simply returns nothing, which
prevents IDOR (insecure direct object reference) attacks.

User and session management methods are user-independent and live on the same
store for convenience.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    text,
)
from sqlalchemy.engine import Engine

from magpie.config import settings
from magpie.knowledge.models import (
    CardStatus,
    Domain,
    LearnedTopic,
    Skill,
    TopicCard,
)

# --- schema (portable DDL: SQLite AUTOINCREMENT / Postgres SERIAL handled here) ---
metadata = MetaData()

user_t = Table(
    "user", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", Text, nullable=False, unique=True),
    Column("password_hash", Text),                       # NULL for OAuth-only
    Column("google_sub", Text, unique=True),             # NULL for password-only
    Column("display_name", Text, nullable=False, server_default=text("''")),
    Column("created_at", Text, nullable=False),
)

session_t = Table(
    "session", metadata,
    Column("token", Text, primary_key=True),
    Column("user_id", Integer,
           ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
)

domain_t = Table(
    "domain", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer,
           ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("weight", Float, nullable=False, server_default=text("1.0")),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("user_id", "name"),
)

skill_t = Table(
    "skill", metadata,
    Column("id", Integer, primary_key=True),
    Column("domain_id", Integer, ForeignKey("domain.id", ondelete="CASCADE")),
    Column("name", Text, nullable=False),
    Column("proficiency", Integer, nullable=False, server_default=text("1")),
    Column("created_at", Text, nullable=False),
    UniqueConstraint("domain_id", "name"),
)

learned_topic_t = Table(
    "learned_topic", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer,
           ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("title", Text, nullable=False),
    Column("summary", Text, nullable=False, server_default=text("''")),
    Column("source_url", Text),
    Column("tags", Text, nullable=False, server_default=text("'[]'")),
    Column("domain_id", Integer, ForeignKey("domain.id", ondelete="SET NULL")),
    Column("embedding", Text),
    Column("learned_at", Text, nullable=False),
)

run_t = Table(
    "run", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer,
           ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
    Column("prompt", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'running'")),
    Column("created_at", Text, nullable=False),
)

topic_card_t = Table(
    "topic_card", metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("run.id", ondelete="CASCADE")),
    Column("title", Text, nullable=False),
    Column("overview", Text, nullable=False, server_default=text("''")),
    Column("why_relevant", Text, nullable=False, server_default=text("''")),
    Column("links", Text, nullable=False, server_default=text("'[]'")),
    Column("tags", Text, nullable=False, server_default=text("'[]'")),
    Column("source_url", Text),
    Column("recency", Text),
    Column("relevance_score", Float, nullable=False, server_default=text("0.0")),
    Column("status", Text, nullable=False, server_default=text("'surfaced'")),
)

signal_t = Table(
    "signal", metadata,
    Column("id", Integer, primary_key=True),
    Column("topic_card_id", Integer, ForeignKey("topic_card.id", ondelete="CASCADE")),
    Column("type", Text, nullable=False),
    Column("value", Float),
    Column("created_at", Text, nullable=False),
)

Index("idx_domain_user", domain_t.c.user_id)
Index("idx_learned_user", learned_topic_t.c.user_id)
Index("idx_run_user", run_t.c.user_id)
Index("idx_session_user", session_t.c.user_id)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# How each feedback signal nudges source/tag preference. Positive = surface more.
SIGNAL_WEIGHTS = {
    "thumbs_up": 1.0,
    "learned": 1.0,
    "thumbs_down": -1.0,
    "too_basic": -0.6,
    "too_advanced": -0.3,
    "irrelevant": -1.5,
}


def _host(url: str | None) -> str | None:
    if not url:
        return None
    return urlparse(url).netloc or None


# --- engine cache (one pooled engine per database URL, shared across stores) ---
_ENGINES: dict[str, Engine] = {}


def _sqlite_url_for(db_path: str) -> str:
    return f"sqlite:///{Path(db_path).as_posix()}"


def _get_engine(url: str) -> Engine:
    engine = _ENGINES.get(url)
    if engine is not None:
        return engine
    if url.startswith("sqlite"):
        # File path lives after sqlite:/// — ensure the parent dir exists.
        path = url.replace("sqlite:///", "", 1)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _enable_fk(dbapi_conn, _record):  # cascade deletes need FK enforcement
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    else:
        engine = create_engine(url, pool_pre_ping=True)
    _ENGINES[url] = engine
    return engine


class OwnershipError(PermissionError):
    """Raised when a write targets a row the bound user does not own."""


class KnowledgeStore:
    def __init__(self, db_path: str | None = None, user_id: int | None = None) -> None:
        # Precedence: explicit db_path (always SQLite, used by tests/CLI) >
        # DATABASE_URL (Postgres for deploy) > settings.db_path (SQLite default).
        if db_path is not None:
            self._url = _sqlite_url_for(db_path)
            self.db_path = db_path
        elif settings.database_url:
            self._url = settings.database_url
            self.db_path = settings.database_url
        else:
            self._url = _sqlite_url_for(settings.db_path)
            self.db_path = settings.db_path
        self.user_id = user_id

    @property
    def _engine(self) -> Engine:
        return _get_engine(self._url)

    def for_user(self, user_id: int) -> KnowledgeStore:
        """Return a new store bound to ``user_id`` (same database)."""
        clone = KnowledgeStore.__new__(KnowledgeStore)
        clone._url = self._url
        clone.db_path = self.db_path
        clone.user_id = user_id
        return clone

    def _uid(self) -> int:
        if self.user_id is None:
            raise OwnershipError("KnowledgeStore is not bound to a user.")
        return self.user_id

    def init_db(self) -> None:
        """Create tables if they don't exist."""
        metadata.create_all(self._engine)

    # ------------------------------------------------------------------ #
    #  User & session management (not user-scoped)                        #
    # ------------------------------------------------------------------ #
    def create_user(
        self,
        email: str,
        password_hash: str | None = None,
        google_sub: str | None = None,
        display_name: str = "",
    ) -> int:
        with self._engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO \"user\" (email, password_hash, google_sub, "
                    "display_name, created_at) "
                    "VALUES (:email, :ph, :gsub, :dn, :now) RETURNING id"
                ),
                {
                    "email": email.lower().strip(), "ph": password_hash,
                    "gsub": google_sub, "dn": display_name, "now": _now(),
                },
            ).scalar_one()

    def get_user(self, user_id: int) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text('SELECT * FROM "user" WHERE id=:id'), {"id": user_id}
            ).mappings().first()
        return dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text('SELECT * FROM "user" WHERE email=:email'),
                {"email": email.lower().strip()},
            ).mappings().first()
        return dict(row) if row else None

    def get_user_by_google_sub(self, google_sub: str) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text('SELECT * FROM "user" WHERE google_sub=:gsub'),
                {"gsub": google_sub},
            ).mappings().first()
        return dict(row) if row else None

    def link_google_sub(self, user_id: int, google_sub: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text('UPDATE "user" SET google_sub=:gsub WHERE id=:id'),
                {"gsub": google_sub, "id": user_id},
            )

    def create_session(self, user_id: int, token: str, ttl_days: int) -> None:
        expires = datetime.now(timezone.utc) + timedelta(days=ttl_days)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO session (token, user_id, created_at, expires_at) "
                    "VALUES (:token, :uid, :now, :exp)"
                ),
                {"token": token, "uid": user_id, "now": _now(),
                 "exp": expires.isoformat()},
            )

    def session_user(self, token: str) -> dict | None:
        """Return the user for a valid, unexpired session token, else None."""
        if not token:
            return None
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    'SELECT u.*, s.expires_at FROM session s '
                    'JOIN "user" u ON u.id = s.user_id WHERE s.token=:token'
                ),
                {"token": token},
            ).mappings().first()
        if not row:
            return None
        d = dict(row)
        if datetime.fromisoformat(d.pop("expires_at")) < datetime.now(timezone.utc):
            self.delete_session(token)
            return None
        return d

    def delete_session(self, token: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM session WHERE token=:token"), {"token": token}
            )

    def purge_expired_sessions(self) -> int:
        with self._engine.begin() as conn:
            return conn.execute(
                text("DELETE FROM session WHERE expires_at < :now"), {"now": _now()}
            ).rowcount

    # ------------------------------------------------------------------ #
    #  Ownership guards                                                   #
    # ------------------------------------------------------------------ #
    def _owns_domain(self, conn, domain_id: int) -> bool:
        return conn.execute(
            text("SELECT 1 FROM domain WHERE id=:id AND user_id=:uid"),
            {"id": domain_id, "uid": self._uid()},
        ).first() is not None

    def _owns_run(self, conn, run_id: int) -> bool:
        return conn.execute(
            text("SELECT 1 FROM run WHERE id=:id AND user_id=:uid"),
            {"id": run_id, "uid": self._uid()},
        ).first() is not None

    def _owns_card(self, conn, card_id: int) -> bool:
        return conn.execute(
            text(
                "SELECT 1 FROM topic_card c JOIN run r ON r.id = c.run_id "
                "WHERE c.id=:id AND r.user_id=:uid"
            ),
            {"id": card_id, "uid": self._uid()},
        ).first() is not None

    # ------------------------------------------------------------------ #
    #  Writes (user-scoped)                                               #
    # ------------------------------------------------------------------ #
    def add_domain(self, name: str, weight: float | None = None) -> int:
        """Insert a domain. On re-add, weight is only changed when explicitly given."""
        with self._engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO domain (user_id, name, weight, created_at) "
                    "VALUES (:uid, :name, :weight, :now) "
                    "ON CONFLICT (user_id, name) DO UPDATE "
                    "SET weight=COALESCE(:weight_upd, domain.weight) RETURNING id"
                ),
                {
                    "uid": self._uid(), "name": name,
                    "weight": weight if weight is not None else 1.0,
                    "weight_upd": weight, "now": _now(),
                },
            ).scalar_one()

    def add_skill(self, domain_id: int, name: str, proficiency: int = 1) -> int:
        with self._engine.begin() as conn:
            if not self._owns_domain(conn, domain_id):
                raise OwnershipError("domain does not belong to this user")
            return conn.execute(
                text(
                    "INSERT INTO skill (domain_id, name, proficiency, created_at) "
                    "VALUES (:did, :name, :prof, :now) "
                    "ON CONFLICT (domain_id, name) DO UPDATE "
                    "SET proficiency=excluded.proficiency RETURNING id"
                ),
                {"did": domain_id, "name": name, "prof": proficiency, "now": _now()},
            ).scalar_one()

    def add_learned_topic(
        self,
        title: str,
        summary: str = "",
        source_url: str | None = None,
        tags: list[str] | None = None,
        domain_id: int | None = None,
        embedding: list[float] | None = None,
    ) -> int:
        with self._engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO learned_topic "
                    "(user_id, title, summary, source_url, tags, domain_id, "
                    " embedding, learned_at) "
                    "VALUES (:uid, :title, :summary, :url, :tags, :did, :emb, :now) "
                    "RETURNING id"
                ),
                {
                    "uid": self._uid(), "title": title, "summary": summary,
                    "url": source_url, "tags": json.dumps(tags or []),
                    "did": domain_id,
                    "emb": json.dumps(embedding) if embedding is not None else None,
                    "now": _now(),
                },
            ).scalar_one()

    def create_run(self, prompt: str) -> int:
        with self._engine.begin() as conn:
            return conn.execute(
                text(
                    "INSERT INTO run (user_id, prompt, status, created_at) "
                    "VALUES (:uid, :prompt, 'running', :now) RETURNING id"
                ),
                {"uid": self._uid(), "prompt": prompt, "now": _now()},
            ).scalar_one()

    def finish_run(self, run_id: int, status: str = "done") -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE run SET status=:status WHERE id=:id AND user_id=:uid"),
                {"status": status, "id": run_id, "uid": self._uid()},
            )

    def save_card(self, card: TopicCard) -> int:
        with self._engine.begin() as conn:
            if card.run_id is None or not self._owns_run(conn, card.run_id):
                raise OwnershipError("run does not belong to this user")
            return conn.execute(
                text(
                    "INSERT INTO topic_card "
                    "(run_id, title, overview, why_relevant, links, tags, "
                    " source_url, recency, relevance_score, status) "
                    "VALUES (:run_id, :title, :overview, :why, :links, :tags, "
                    " :url, :recency, :score, :status) RETURNING id"
                ),
                {
                    "run_id": card.run_id, "title": card.title,
                    "overview": card.overview, "why": card.why_relevant,
                    "links": json.dumps(card.links), "tags": json.dumps(card.tags),
                    "url": card.source_url, "recency": card.recency,
                    "score": card.relevance_score, "status": card.status.value,
                },
            ).scalar_one()

    def set_card_status(self, card_id: int, status: CardStatus) -> None:
        with self._engine.begin() as conn:
            if not self._owns_card(conn, card_id):
                raise OwnershipError("card does not belong to this user")
            conn.execute(
                text("UPDATE topic_card SET status=:status WHERE id=:id"),
                {"status": status.value, "id": card_id},
            )

    # --- deletes (user-scoped) ---
    def forget_topic(self, topic_id: int) -> bool:
        with self._engine.begin() as conn:
            res = conn.execute(
                text("DELETE FROM learned_topic WHERE id=:id AND user_id=:uid"),
                {"id": topic_id, "uid": self._uid()},
            )
        return res.rowcount > 0

    def forget_topic_by_title(self, title: str) -> int:
        with self._engine.begin() as conn:
            res = conn.execute(
                text(
                    "DELETE FROM learned_topic "
                    "WHERE lower(title)=lower(:title) AND user_id=:uid"
                ),
                {"title": title, "uid": self._uid()},
            )
        return res.rowcount

    def delete_run(self, run_id: int) -> bool:
        with self._engine.begin() as conn:
            res = conn.execute(
                text("DELETE FROM run WHERE id=:id AND user_id=:uid"),
                {"id": run_id, "uid": self._uid()},
            )
        return res.rowcount > 0

    # --- feedback signals ---
    def add_signal(self, card_id: int, signal_type: str, value: float | None = None) -> int:
        with self._engine.begin() as conn:
            if not self._owns_card(conn, card_id):
                raise OwnershipError("card does not belong to this user")
            return conn.execute(
                text(
                    "INSERT INTO signal (topic_card_id, type, value, created_at) "
                    "VALUES (:cid, :type, :value, :now) RETURNING id"
                ),
                {"cid": card_id, "type": signal_type, "value": value, "now": _now()},
            ).scalar_one()

    def _signal_rows(self) -> list[dict]:
        with self._engine.connect() as conn:
            return [
                dict(r) for r in conn.execute(
                    text(
                        "SELECT c.source_url, c.tags, s.type "
                        "FROM signal s JOIN topic_card c ON c.id = s.topic_card_id "
                        "JOIN run r ON r.id = c.run_id WHERE r.user_id=:uid"
                    ),
                    {"uid": self._uid()},
                ).mappings().all()
            ]

    def source_scores(self) -> dict[str, float]:
        """Per-host preference in [-1, 1] aggregated from this user's feedback."""
        totals: dict[str, float] = {}
        for r in self._signal_rows():
            host = _host(r["source_url"])
            if not host:
                continue
            totals[host] = totals.get(host, 0.0) + SIGNAL_WEIGHTS.get(r["type"], 0.0)
        return {h: math.tanh(v) for h, v in totals.items()}

    def tag_scores(self) -> dict[str, float]:
        """Per-tag preference in [-1, 1] aggregated from this user's feedback."""
        totals: dict[str, float] = {}
        for r in self._signal_rows():
            w = SIGNAL_WEIGHTS.get(r["type"], 0.0)
            for tag in json.loads(r["tags"] or "[]"):
                totals[tag] = totals.get(tag, 0.0) + w
        return {t: math.tanh(v) for t, v in totals.items()}

    # ------------------------------------------------------------------ #
    #  Reads (user-scoped)                                                #
    # ------------------------------------------------------------------ #
    def list_domains(self) -> list[Domain]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, name, weight, created_at FROM domain "
                    "WHERE user_id=:uid ORDER BY weight DESC"
                ),
                {"uid": self._uid()},
            ).mappings().all()
        return [Domain(**dict(r)) for r in rows]

    def list_skills(self, domain_id: int | None = None) -> list[Skill]:
        with self._engine.connect() as conn:
            if domain_id is None:
                rows = conn.execute(
                    text(
                        "SELECT s.id, s.domain_id, s.name, s.proficiency, s.created_at "
                        "FROM skill s JOIN domain d ON d.id = s.domain_id "
                        "WHERE d.user_id=:uid ORDER BY s.name"
                    ),
                    {"uid": self._uid()},
                ).mappings().all()
            else:
                rows = conn.execute(
                    text(
                        "SELECT s.id, s.domain_id, s.name, s.proficiency, s.created_at "
                        "FROM skill s JOIN domain d ON d.id = s.domain_id "
                        "WHERE d.user_id=:uid AND s.domain_id=:did ORDER BY s.name"
                    ),
                    {"uid": self._uid(), "did": domain_id},
                ).mappings().all()
        return [Skill(**dict(r)) for r in rows]

    def list_learned(self, limit: int = 50) -> list[LearnedTopic]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, title, summary, source_url, tags, domain_id, learned_at "
                    "FROM learned_topic WHERE user_id=:uid "
                    "ORDER BY learned_at DESC LIMIT :lim"
                ),
                {"uid": self._uid(), "lim": limit},
            ).mappings().all()
        out: list[LearnedTopic] = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d.get("tags") or "[]")
            out.append(LearnedTopic(**d))
        return out

    def profile(self) -> dict:
        """Return domains + skills + recent learned topics for prompt context."""
        domains = self.list_domains()
        return {
            "domains": [
                {
                    "name": d.name,
                    "weight": d.weight,
                    "skills": [s.name for s in self.list_skills(d.id)],
                }
                for d in domains
            ],
            "learned": [t.title for t in self.list_learned(limit=50)],
        }

    def learned_titles(self) -> list[str]:
        """Used for dedup — what the user already knows."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT title FROM learned_topic WHERE user_id=:uid"),
                {"uid": self._uid()},
            ).mappings().all()
        return [r["title"] for r in rows]

    def list_runs(self, limit: int = 50, dedupe: bool = True) -> list[dict]:
        """Return this user's past discovery runs (newest first) with card counts."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT r.id, r.prompt, r.status, r.created_at, "
                    "       COUNT(c.id) AS cards "
                    "FROM run r LEFT JOIN topic_card c ON c.run_id = r.id "
                    "WHERE r.user_id=:uid GROUP BY r.id, r.prompt, r.status, "
                    "r.created_at ORDER BY r.created_at DESC"
                ),
                {"uid": self._uid()},
            ).mappings().all()
        runs = [dict(r) for r in rows]
        if dedupe:
            seen: set[str] = set()
            deduped = []
            for r in runs:
                key = r["prompt"].strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(r)
            runs = deduped
        return runs[:limit]

    def get_run(self, run_id: int) -> dict | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM run WHERE id=:id AND user_id=:uid"),
                {"id": run_id, "uid": self._uid()},
            ).mappings().first()
        return dict(row) if row else None

    def get_run_cards(self, run_id: int) -> list[TopicCard]:
        """Reconstruct Topic Cards for a run the user owns; empty if not theirs."""
        with self._engine.connect() as conn:
            if not self._owns_run(conn, run_id):
                return []
            rows = conn.execute(
                text(
                    "SELECT * FROM topic_card WHERE run_id=:rid "
                    "ORDER BY relevance_score DESC"
                ),
                {"rid": run_id},
            ).mappings().all()
        cards: list[TopicCard] = []
        for r in rows:
            d = dict(r)
            cards.append(
                TopicCard(
                    id=d["id"],
                    run_id=d["run_id"],
                    title=d["title"],
                    overview=d["overview"],
                    why_relevant=d["why_relevant"],
                    links=json.loads(d["links"] or "[]"),
                    tags=json.loads(d["tags"] or "[]"),
                    source_url=d["source_url"],
                    recency=d["recency"],
                    relevance_score=d["relevance_score"],
                    status=CardStatus(d["status"]),
                )
            )
        return cards
