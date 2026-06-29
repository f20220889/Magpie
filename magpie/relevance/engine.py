"""Score & rank candidates against the user's KB and current prompt.

Pipeline:
  1. Build a query vector from the prompt + the user's domains/skills.
  2. Embed each Topic Card (title + overview + tags).
  3. Score = cosine similarity to the query (embeddings are L2-normalized,
     so cosine is a plain dot product).
  4. Dedup: compare each card to the user's already-learned topics. Cards
     that are near-duplicates are penalized; very-close ones are dropped
     (the user already knows them).
  5. Sort by final score, descending.

Embeddings come from a free, local sentence-transformers model. The embedder
is injectable (``embed_fn``) so this class is testable without a model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from urllib.parse import urlparse

from magpie.knowledge.models import TopicCard

# Cosine thresholds (embeddings normalized -> dot product in [-1, 1]).
DROP_THRESHOLD = 0.88   # >= this vs a learned topic => already known, drop it
PENALTY_THRESHOLD = 0.70  # >= this => partial overlap, down-rank
PENALTY_WEIGHT = 0.5    # how much overlap subtracts from the score

# How much learned feedback nudges the score (small — relevance still leads).
SOURCE_WEIGHT = 0.10    # per-host preference from signals
TAG_WEIGHT = 0.10       # per-tag preference from signals

EmbedFn = Callable[[list[str]], list[list[float]]]


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _card_text(card: TopicCard) -> str:
    parts = [card.title, card.overview, " ".join(card.tags)]
    return " ".join(p for p in parts if p).strip()


def _profile_text(prompt: str, profile: dict) -> str:
    skills = [s for d in profile.get("domains", []) for s in d.get("skills", [])]
    domains = [d.get("name", "") for d in profile.get("domains", [])]
    return " ".join([prompt, *domains, *skills]).strip()


class RelevanceEngine:
    def __init__(self, embed_fn: EmbedFn | None = None) -> None:
        self._embed_fn = embed_fn

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embed_fn is not None:
            return self._embed_fn(texts)
        from magpie.relevance.embeddings import embed  # lazy: loads the model

        return embed(texts)

    def rank(
        self,
        cards: list[TopicCard],
        prompt: str,
        profile: dict,
        learned_titles: list[str],
        source_scores: dict[str, float] | None = None,
        tag_scores: dict[str, float] | None = None,
    ) -> list[TopicCard]:
        """Return cards sorted by relevance, deduped against learned topics.

        ``source_scores`` / ``tag_scores`` are per-host / per-tag preferences in
        [-1, 1] learned from user feedback; they apply a small boost/penalty so
        ranking adapts over time without overriding semantic relevance.
        """
        if not cards:
            return []
        source_scores = source_scores or {}
        tag_scores = tag_scores or {}

        query_text = _profile_text(prompt, profile)
        card_texts = [_card_text(c) for c in cards]

        # Single batched embed call: [query] + cards + learned titles.
        all_texts = [query_text] + card_texts + learned_titles
        vecs = self._embed(all_texts)

        query_vec = vecs[0]
        card_vecs = vecs[1 : 1 + len(cards)]
        learned_vecs = vecs[1 + len(cards) :]

        ranked: list[TopicCard] = []
        for card, cvec in zip(cards, card_vecs):
            score = _dot(cvec, query_vec)

            # Dedup against what the user already knows.
            max_known = max((_dot(cvec, lv) for lv in learned_vecs), default=0.0)
            if max_known >= DROP_THRESHOLD:
                continue  # already known — don't surface
            if max_known >= PENALTY_THRESHOLD:
                score -= PENALTY_WEIGHT * (max_known - PENALTY_THRESHOLD)

            # Feedback-learned nudges: preferred sources/tags rise, disliked sink.
            host = urlparse(card.source_url or "").netloc
            score += SOURCE_WEIGHT * source_scores.get(host, 0.0)
            if card.tags:
                tag_pref = sum(tag_scores.get(t, 0.0) for t in card.tags) / len(card.tags)
                score += TAG_WEIGHT * tag_pref

            card.relevance_score = round(score, 4)
            ranked.append(card)

        ranked.sort(key=lambda c: c.relevance_score, reverse=True)
        return ranked
