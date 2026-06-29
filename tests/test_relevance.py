"""Ranking logic tests with a deterministic fake embedder (no model download)."""

import math

from magpie.knowledge.models import TopicCard
from magpie.relevance.engine import RelevanceEngine

PROFILE = {"domains": [{"name": "Backend", "skills": ["Python"]}]}


def _unit(vec):
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def _card(title):
    return TopicCard(title=title, overview="", why_relevant="", tags=[])


def make_embedder(mapping):
    """mapping: text-substring -> raw vector. Returns normalized vectors."""

    def embed(texts):
        out = []
        for t in texts:
            vec = next((v for key, v in mapping.items() if key in t), [0.0, 0.0, 0.0])
            out.append(_unit(vec))
        return out

    return embed


def test_ranks_by_similarity_to_query():
    # query points along x; "near" card aligns, "far" card is orthogonal.
    embed = make_embedder(
        {"QUERY": [1, 0, 0], "near": [1, 0, 0], "far": [0, 1, 0]}
    )
    eng = RelevanceEngine(embed_fn=embed)
    ranked = eng.rank([_card("far"), _card("near")], "QUERY", PROFILE, [])
    assert [c.title for c in ranked] == ["near", "far"]
    assert ranked[0].relevance_score > ranked[1].relevance_score


def test_drops_already_known():
    # "dup" card is identical to a learned topic -> dropped.
    embed = make_embedder(
        {"QUERY": [1, 0, 0], "dup": [1, 0, 0], "KNOWN": [1, 0, 0]}
    )
    eng = RelevanceEngine(embed_fn=embed)
    ranked = eng.rank([_card("dup")], "QUERY", PROFILE, ["KNOWN topic"])
    assert ranked == []


def test_penalizes_partial_overlap():
    # card partially overlaps a known topic -> still surfaced but down-ranked.
    embed = make_embedder(
        {"QUERY": [1, 0, 0], "overlap": [1, 0, 0], "KNOWN": [0.8, 0.6, 0]}
    )
    eng = RelevanceEngine(embed_fn=embed)
    with_known = eng.rank([_card("overlap")], "QUERY", PROFILE, ["KNOWN"])[0]
    without = eng.rank([_card("overlap")], "QUERY", PROFILE, [])[0]
    assert with_known.relevance_score < without.relevance_score


def test_empty_cards():
    assert RelevanceEngine(embed_fn=lambda t: []).rank([], "q", PROFILE, []) == []


def test_min_score_drops_off_topic():
    # "off" is orthogonal to the query (score 0); a floor above 0 drops it.
    embed = make_embedder({"QUERY": [1, 0, 0], "on": [1, 0, 0], "off": [0, 1, 0]})
    eng = RelevanceEngine(embed_fn=embed)
    ranked = eng.rank([_card("on"), _card("off")], "QUERY", PROFILE, [], min_score=0.5)
    assert [c.title for c in ranked] == ["on"]


def test_dedup_collapses_near_identical_cards():
    # two cards with (near-)identical vectors -> only the first survives dedup.
    embed = make_embedder({"QUERY": [1, 0, 0], "a": [1, 0, 0], "b": [1, 0, 0]})
    eng = RelevanceEngine(embed_fn=embed)
    cards = [_card("a"), _card("b")]
    assert len(eng.rank(cards, "QUERY", PROFILE, [])) == 2  # off by default
    deduped = eng.rank(cards, "QUERY", PROFILE, [], dedup_threshold=0.92)
    assert len(deduped) == 1


def test_shortlist_picks_most_relevant():
    embed = make_embedder(
        {"QUERY": [1, 0, 0], "hit": [1, 0, 0], "miss": [0, 1, 0]}
    )
    eng = RelevanceEngine(embed_fn=embed)
    cands = [("miss", "http://m", "miss"), ("hit", "http://h", "hit")]
    picked = eng.shortlist(cands, "QUERY", PROFILE, k=1)
    assert [c[1] for c in picked] == ["http://h"]


def test_shortlist_skips_embed_when_under_k():
    # When pool <= k there is nothing to trim, so it must not even embed.
    def boom(texts):
        raise AssertionError("should not embed when pool <= k")

    eng = RelevanceEngine(embed_fn=boom)
    cands = [("a", "http://a", "s")]
    assert eng.shortlist(cands, "QUERY", PROFILE, k=8) == cands
