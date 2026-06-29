"""Scheduled digest: run discoveries automatically and collect the best cards.

Seeds prompts from the adjacency suggester (what to learn next), runs each
through the normal discovery loop, and returns the top cards across runs.
Designed to be invoked on a schedule (cron / launchd) — see README.
"""

from __future__ import annotations

from collections.abc import Callable

from magpie.agent.adjacency import AdjacencySuggester
from magpie.agent.orchestrator import Orchestrator
from magpie.knowledge.models import TopicCard
from magpie.knowledge.store import KnowledgeStore

Progress = Callable[[str, str], None]


def _noop(stage: str, message: str) -> None:  # pragma: no cover
    pass


class DigestRunner:
    def __init__(self, store: KnowledgeStore | None = None) -> None:
        self.store = store or KnowledgeStore()
        self.suggester = AdjacencySuggester()
        self.orchestrator = Orchestrator(store=self.store)

    def run(
        self, max_prompts: int = 3, per_prompt: int = 3, progress: Progress = _noop
    ) -> dict:
        """Run up to ``max_prompts`` auto-seeded discoveries.

        Returns {"prompts": [...], "cards": [TopicCard...]} with the top cards
        across all runs (already persisted by the orchestrator).
        """
        self.store.init_db()
        profile = self.store.profile()
        learned = self.store.learned_titles()

        progress("suggest", "deciding what to explore next")
        suggestions = self.suggester.suggest(profile, learned, n=max_prompts)
        prompts = [s["topic"] for s in suggestions] or [
            f"latest developments in {d['name']}" for d in profile.get("domains", [])
        ][:max_prompts]

        all_cards: list[TopicCard] = []
        for p in prompts[:max_prompts]:
            progress("discover", p)
            try:
                cards = self.orchestrator.run(p, progress=progress)[:per_prompt]
            except Exception:
                continue
            all_cards.extend(cards)

        all_cards.sort(key=lambda c: c.relevance_score, reverse=True)
        return {"prompts": prompts[:max_prompts], "cards": all_cards}
