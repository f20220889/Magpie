"""Postgres integration for the store. Skipped unless a DSN is provided.

Run locally against a throwaway Postgres, e.g.::

    docker run -d --name pg -e POSTGRES_PASSWORD=magpie -e POSTGRES_DB=magpie \\
        -p 55432:5432 postgres:16-alpine
    MAGPIE_TEST_DATABASE_URL=postgresql+psycopg://postgres:magpie@localhost:55432/magpie \\
        pytest tests/test_store_postgres.py -q

Proves the same code path works on Postgres: SERIAL DDL, ON CONFLICT upsert +
RETURNING, ownership/IDOR guards, sessions, and FK cascade deletes.
"""

from __future__ import annotations

import os

import pytest

from magpie.knowledge.models import TopicCard

PG_URL = os.getenv("MAGPIE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set MAGPIE_TEST_DATABASE_URL")


@pytest.fixture
def pg_store(monkeypatch):
    from magpie.config import settings
    from magpie.knowledge import store as store_mod

    monkeypatch.setattr(settings, "database_url", PG_URL)
    engine = store_mod._get_engine(PG_URL)
    store_mod.metadata.drop_all(engine)   # clean slate
    store_mod.metadata.create_all(engine)
    return store_mod.KnowledgeStore()


def test_postgres_crud_isolation_and_cascade(pg_store):
    from magpie.knowledge.store import OwnershipError

    a = pg_store.create_user(email="alice@x.com", password_hash="h")
    b = pg_store.create_user(email="bob@x.com", password_hash="h")
    A, B = pg_store.for_user(a), pg_store.for_user(b)

    # upsert via ON CONFLICT ... RETURNING
    d = A.add_domain("Backend")
    assert A.add_domain("Backend", weight=2.0) == d
    assert A.list_domains()[0].weight == 2.0

    rid = A.create_run("python news")
    cid = A.save_card(TopicCard(
        run_id=rid, title="T", overview="o", why_relevant="w",
        tags=["py"], links=["http://u"], source_url="http://u",
    ))
    A.add_signal(cid, "thumbs_up")

    # IDOR: B sees nothing of A's and cannot write A's card
    assert B.get_run(rid) is None
    assert B.get_run_cards(rid) == []
    with pytest.raises(OwnershipError):
        B.add_signal(cid, "thumbs_up")

    # sessions
    pg_store.create_session(a, "tok", 14)
    assert pg_store.session_user("tok")["email"] == "alice@x.com"

    # FK cascade: deleting the run removes its cards
    A.delete_run(rid)
    assert A.get_run_cards(rid) == []
