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
