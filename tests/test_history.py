"""Tests for run history persistence + dedup + restore."""

from magpie.knowledge.models import TopicCard
from magpie.knowledge.store import KnowledgeStore


def _store(tmp_path):
    s = KnowledgeStore(db_path=str(tmp_path / "h.db"))
    s.init_db()
    return s.for_user(s.create_user(email="u@test.local"))


def _save_run(store, prompt, titles):
    rid = store.create_run(prompt)
    for i, t in enumerate(titles):
        store.save_card(
            TopicCard(run_id=rid, title=t, overview="o", why_relevant="w",
                      relevance_score=1.0 - i * 0.1, links=[f"http://{t}"], tags=["x"])
        )
    store.finish_run(rid)
    return rid


def test_list_runs_counts_cards(tmp_path):
    s = _store(tmp_path)
    _save_run(s, "python async", ["A", "B"])
    runs = s.list_runs()
    assert len(runs) == 1
    assert runs[0]["prompt"] == "python async"
    assert runs[0]["cards"] == 2


def test_list_runs_dedupes_by_prompt(tmp_path):
    s = _store(tmp_path)
    _save_run(s, "Kubernetes", ["A"])
    _save_run(s, "kubernetes", ["B", "C"])   # same prompt (case-insensitive)
    _save_run(s, "Postgres", ["D"])
    deduped = s.list_runs(dedupe=True)
    assert [r["prompt"] for r in deduped] == ["Postgres", "kubernetes"]  # newest-first
    assert len(s.list_runs(dedupe=False)) == 3


def test_get_run_cards_restores_ranked(tmp_path):
    s = _store(tmp_path)
    rid = _save_run(s, "x", ["High", "Low"])  # High has higher relevance
    cards = s.get_run_cards(rid)
    assert [c.title for c in cards] == ["High", "Low"]
    assert cards[0].links == ["http://High"]
    assert cards[0].tags == ["x"]


def test_delete_run_cascades_cards(tmp_path):
    s = _store(tmp_path)
    rid = _save_run(s, "gone", ["A", "B"])
    assert s.delete_run(rid) is True
    assert s.get_run(rid) is None
    assert s.get_run_cards(rid) == []          # cards cascade-deleted
    assert s.delete_run(rid) is False          # already gone


def test_forget_topic(tmp_path):
    s = _store(tmp_path)
    tid = s.add_learned_topic("Async TaskGroup", "x")
    s.add_learned_topic("Docker", "y")
    assert s.forget_topic(tid) is True
    assert "Async TaskGroup" not in s.learned_titles()
    assert s.forget_topic(tid) is False        # already gone


def test_forget_by_title_case_insensitive(tmp_path):
    s = _store(tmp_path)
    s.add_learned_topic("Kubernetes", "x")
    assert s.forget_topic_by_title("kubernetes") == 1
    assert s.learned_titles() == []
