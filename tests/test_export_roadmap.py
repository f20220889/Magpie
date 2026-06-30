"""Exporter formatting + roadmap normalization."""

from magpie import exporter
from magpie.agent.roadmap import RoadmapBuilder

TOPICS = [
    {"title": "Async TaskGroup", "summary": "structured concurrency",
     "source_url": "http://x", "tags": ["python", "async io"]},
    {"title": "Tabs\tand\nnewlines", "summary": "messy\tvalue", "tags": []},
]


def test_export_json_roundtrips():
    import json
    assert json.loads(exporter.to_json(TOPICS)) == TOPICS


def test_export_markdown():
    md = exporter.to_markdown(TOPICS)
    assert "## Async TaskGroup" in md
    assert "#python #async-io" in md          # spaces -> dashes
    assert "Source: <http://x>" in md


def test_export_anki_tsv_is_clean():
    tsv = exporter.to_anki_tsv(TOPICS)
    rows = [r for r in tsv.splitlines() if r]
    assert "\t" in rows[0]
    # tabs/newlines inside fields must be neutralized so rows stay aligned
    assert all(len(r.split("\t")) == 3 for r in rows)
    assert "Source: http://x" in rows[0]


def test_export_unknown_format():
    import pytest
    with pytest.raises(ValueError):
        exporter.export(TOPICS, "pdf")


def test_roadmap_orders_and_dedupes(make_llm):
    llm = make_llm({"roadmap": [
        {"topic": "Step A", "reason": "first"},
        {"topic": "step a", "reason": "dup"},     # dropped
        {"topic": "Step B", "reason": "second"},
    ]})
    out = RoadmapBuilder(llm=llm).build({"domains": []}, [])
    assert [s["step"] for s in out] == [1, 2]
    assert [s["topic"] for s in out] == ["Step A", "Step B"]


def test_roadmap_caps(make_llm):
    llm = make_llm({"roadmap": [{"topic": f"T{i}"} for i in range(20)]})
    assert len(RoadmapBuilder(llm=llm).build({"domains": []}, [], n=4)) == 4


def _authed_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from magpie.config import settings
    from magpie.web.server import app

    monkeypatch.setattr(settings, "db_path", str(tmp_path / "llmfail.db"))
    c = TestClient(app)
    r = c.post("/api/auth/signup", json={"email": "p@t.local", "password": "password123"})
    assert r.status_code == 200, r.text
    return c


def test_suggestions_llm_error_returns_503_not_500(tmp_path, monkeypatch):
    import magpie.agent.adjacency as adj
    from magpie.llm.base import LLMError

    def boom(self, *a, **k):
        raise LLMError("groq: no API key. Set GROQ_API_KEY.")

    monkeypatch.setattr(adj.AdjacencySuggester, "suggest", boom)
    r = _authed_client(tmp_path, monkeypatch).get("/api/suggestions")
    assert r.status_code == 503
    assert "API key" in r.json()["detail"]


def test_roadmap_llm_error_returns_503_not_500(tmp_path, monkeypatch):
    import magpie.agent.roadmap as rm
    from magpie.llm.base import LLMError

    def boom(self, *a, **k):
        raise LLMError("groq: no API key.")

    monkeypatch.setattr(rm.RoadmapBuilder, "build", boom)
    r = _authed_client(tmp_path, monkeypatch).get("/api/roadmap")
    assert r.status_code == 503
