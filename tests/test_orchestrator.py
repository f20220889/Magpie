"""End-to-end orchestrator test with all external deps faked (no net/LLM/model)."""

from magpie.agent.orchestrator import Orchestrator
from magpie.knowledge.models import TopicCard
from magpie.knowledge.store import KnowledgeStore
from magpie.search.base import SearchResult


class FakeSearch:
    def search(self, query, max_results=8):
        return [
            SearchResult("Cool New Tool", "http://a", "snippet"),
            SearchResult("Dupe URL", "http://a", "snippet"),  # deduped
            SearchResult("Another", "http://b", "snippet"),
        ]


class FakePlanner:
    def plan(self, prompt, profile, learned, n=5):
        return ["q1", "q2"]


class FakeSummarizer:
    def to_card(self, content, url, profile):
        return TopicCard(
            title=f"Card {url}", overview="o", why_relevant="w",
            tags=["t"], links=[url], source_url=url,
        )


class FakeRanker:
    def shortlist(self, candidates, prompt, profile, k):
        return candidates[:k]  # identity (test pool is smaller than k anyway)

    def rank(self, cards, prompt, profile, learned, **kwargs):
        return cards  # identity


def _build(tmp_path, monkeypatch):
    # Patch the scraper used inside the orchestrator module.
    import magpie.agent.orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "fetch_and_extract", lambda url: "body text")

    store = KnowledgeStore(db_path=str(tmp_path / "t.db"))
    store.init_db()
    uid = store.create_user(email="test@magpie.local")
    store = store.for_user(uid)  # bind to a user — the store is user-scoped
    orch = Orchestrator.__new__(Orchestrator)  # skip real __init__ (no network/model)
    orch.store = store
    orch.search = FakeSearch()
    orch.planner = FakePlanner()
    orch.summarizer = FakeSummarizer()
    orch.ranker = FakeRanker()
    return orch, store


def test_run_dedupes_and_persists(tmp_path, monkeypatch):
    orch, store = _build(tmp_path, monkeypatch)
    cards = orch.run("whats new")
    urls = sorted(c.source_url for c in cards)
    assert urls == ["http://a", "http://b"]   # dupe URL collapsed
    assert all(c.id is not None for c in cards)  # persisted with ids
    assert all(c.run_id is not None for c in cards)


def test_commit_learned_closes_loop(tmp_path, monkeypatch):
    orch, store = _build(tmp_path, monkeypatch)
    cards = orch.run("whats new")
    assert store.learned_titles() == []
    orch.commit_learned(cards[0])
    assert cards[0].title in store.learned_titles()
