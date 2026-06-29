"""Unit tests for planner/summarizer logic using a fake LLM (no Ollama needed)."""

from magpie.agent.query_planner import QueryPlanner
from magpie.summarize.summarizer import Summarizer

PROFILE = {"domains": [{"name": "Backend", "skills": ["Python"]}], "learned": ["REST"]}


def test_planner_normalizes_and_dedupes(make_llm):
    llm = make_llm({"queries": ["  Foo ", "foo", "Bar", 123, ""]})
    planner = QueryPlanner(llm=llm)
    assert planner.plan("x", PROFILE, ["REST"]) == ["Foo", "Bar"]


def test_planner_falls_back_to_prompt(make_llm):
    planner = QueryPlanner(llm=make_llm({"queries": []}))
    assert planner.plan("raw prompt", PROFILE, []) == ["raw prompt"]


def test_planner_caps_results(make_llm):
    llm = make_llm({"queries": [f"q{i}" for i in range(10)]})
    assert len(QueryPlanner(llm=llm).plan("x", PROFILE, [], n=3)) == 3


def test_summarizer_builds_card(make_llm):
    llm = make_llm(
        {"title": "T", "overview": "O", "why_relevant": "W", "tags": ["a", 1, "b"]}
    )
    card = Summarizer(llm=llm).to_card("body", "http://u", PROFILE)
    assert card.title == "T"
    assert card.why_relevant == "W"
    assert card.tags == ["a", "b"]          # non-strings dropped
    assert card.links == ["http://u"]
    assert card.source_url == "http://u"


def test_summarizer_handles_garbage(make_llm):
    card = Summarizer(llm=make_llm("not a dict")).to_card("body", "http://u", PROFILE)
    assert card.title == "http://u"         # falls back to URL
    assert card.tags == []
