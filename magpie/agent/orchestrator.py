"""The discovery loop: context -> plan -> scrape -> summarize -> rank.

Ties together every component. See README §5 "Agentic Learning Loop".
"""

from __future__ import annotations

from collections.abc import Callable

from magpie.agent.query_planner import QueryPlanner
from magpie.config import settings
from magpie.knowledge.models import CardStatus, TopicCard
from magpie.knowledge.store import KnowledgeStore
from magpie.relevance.engine import RelevanceEngine
from magpie.scraper.extractor import fetch_and_extract
from magpie.search.base import get_search_provider
from magpie.summarize.summarizer import Summarizer

# A progress callback: (stage, message) -> None. Lets the CLI show activity.
Progress = Callable[[str, str], None]


def _noop(stage: str, message: str) -> None:  # pragma: no cover
    pass


class Orchestrator:
    def __init__(self, store: KnowledgeStore | None = None) -> None:
        self.store = store or KnowledgeStore()
        self.search = get_search_provider()
        self.planner = QueryPlanner()
        self.summarizer = Summarizer()
        self.ranker = RelevanceEngine()

    def run(self, prompt: str, progress: Progress = _noop) -> list[TopicCard]:
        """Execute one discovery run and return ranked, persisted Topic Cards."""
        self.store.init_db()
        profile = self.store.profile()
        learned = self.store.learned_titles()
        run_id = self.store.create_run(prompt)

        try:
            progress("plan", "planning search queries")
            queries = self.planner.plan(prompt, profile, learned)

            # Gather candidate URLs across queries, deduped, capped.
            seen_urls: set[str] = set()
            candidates: list[tuple[str, str]] = []  # (title, url)
            for q in queries:
                progress("search", f"searching: {q}")
                for r in self.search.search(q, max_results=settings.max_results):
                    if r.url and r.url not in seen_urls:
                        seen_urls.add(r.url)
                        candidates.append((r.title, r.url))
            candidates = candidates[: settings.max_results]

            # Scrape + summarize each candidate; skip failures silently.
            cards: list[TopicCard] = []
            for title, url in candidates:
                progress("scrape", f"reading: {title or url}")
                content = fetch_and_extract(url)
                if not content:
                    continue
                try:
                    card = self.summarizer.to_card(content, url, profile)
                except Exception:
                    continue
                card.run_id = run_id
                cards.append(card)

            progress("rank", f"ranking {len(cards)} cards")
            ranked = self.ranker.rank(
                cards, prompt, profile, learned,
                source_scores=self.store.source_scores(),
                tag_scores=self.store.tag_scores(),
            )

            # Persist surfaced cards (assign DB ids for the learn step).
            for card in ranked:
                card.id = self.store.save_card(card)

            self.store.finish_run(run_id, "done")
            return ranked
        except Exception:
            self.store.finish_run(run_id, "error")
            raise

    def commit_learned(self, card: TopicCard) -> None:
        """Persist a Topic Card as a learned topic — closes the loop."""
        self.store.add_learned_topic(
            title=card.title,
            summary=card.overview,
            source_url=card.source_url,
            tags=card.tags,
        )
        if card.id is not None:
            self.store.set_card_status(card.id, CardStatus.learned)
            self.store.add_signal(card.id, "learned")  # feeds source/tag preference
