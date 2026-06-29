"""Feedback signals → source/tag preference scores → ranking nudge."""

import math

from magpie.knowledge.models import TopicCard
from magpie.knowledge.store import KnowledgeStore
from magpie.relevance.engine import RelevanceEngine

PROFILE = {"domains": [{"name": "Backend", "skills": ["Python"]}]}


def _store(tmp_path):
    s = KnowledgeStore(db_path=str(tmp_path / "s.db"))
    s.init_db()
    return s.for_user(s.create_user(email="u@test.local"))


def _card_in(store, url, tags):
    rid = store.create_run("p")
    return store.save_card(
        TopicCard(run_id=rid, title="t", overview="o", why_relevant="w",
                  source_url=url, links=[url], tags=tags)
    )


def test_source_and_tag_scores_aggregate(tmp_path):
    s = _store(tmp_path)
    good = _card_in(s, "https://good.dev/x", ["python"])
    bad = _card_in(s, "https://bad.io/y", ["php"])
    s.add_signal(good, "thumbs_up")
    s.add_signal(good, "learned")        # good.dev: +2 -> tanh(2)
    s.add_signal(bad, "irrelevant")      # bad.io: -1.5 -> tanh(-1.5)

    src = s.source_scores()
    assert src["good.dev"] == math.tanh(2.0)
    assert src["bad.io"] == math.tanh(-1.5)

    tags = s.tag_scores()
    assert tags["python"] == math.tanh(2.0)
    assert tags["php"] == math.tanh(-1.5)


def test_unknown_signal_type_ignored_in_scoring(tmp_path):
    s = _store(tmp_path)
    cid = _card_in(s, "https://h.dev/a", ["x"])
    s.add_signal(cid, "weird_type")      # weight 0
    assert s.source_scores()["h.dev"] == 0.0


def test_ranking_boosts_preferred_source():
    # Two equally-relevant cards; the one from a preferred host should win.
    def embed(texts):
        # all vectors identical -> equal cosine, so only the nudge differentiates
        return [[1.0, 0.0, 0.0] for _ in texts]

    eng = RelevanceEngine(embed_fn=embed)
    liked = TopicCard(title="A", overview="", why_relevant="",
                      source_url="https://liked.dev/1", tags=[])
    other = TopicCard(title="B", overview="", why_relevant="",
                      source_url="https://other.dev/1", tags=[])
    ranked = eng.rank([other, liked], "q", PROFILE, [],
                      source_scores={"liked.dev": 0.9})
    assert ranked[0].source_url == "https://liked.dev/1"
    assert ranked[0].relevance_score > ranked[1].relevance_score
