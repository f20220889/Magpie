"""Adjacency suggester logic tests with a fake LLM (no Ollama)."""

from magpie.agent.adjacency import AdjacencySuggester

PROFILE = {"domains": [{"name": "Backend", "skills": ["Python"]}]}


def test_normalizes_and_dedupes(make_llm):
    llm = make_llm({"suggestions": [
        {"topic": " asyncio ", "reason": "next step"},
        {"topic": "asyncio", "reason": "dup"},      # case/space dup -> dropped
        {"topic": "FastAPI", "reason": "builds on Python"},
        {"topic": "", "reason": "empty -> dropped"},
        "garbage",                                   # non-dict -> dropped
    ]})
    out = AdjacencySuggester(llm=llm).suggest(PROFILE, ["REST"])
    assert [s["topic"] for s in out] == ["asyncio", "FastAPI"]
    assert out[0]["reason"] == "next step"


def test_caps_results(make_llm):
    llm = make_llm({"suggestions": [{"topic": f"t{i}"} for i in range(10)]})
    assert len(AdjacencySuggester(llm=llm).suggest(PROFILE, [], n=3)) == 3


def test_handles_garbage_payload(make_llm):
    assert AdjacencySuggester(llm=make_llm("not a dict")).suggest(PROFILE, []) == []
