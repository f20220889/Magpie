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
# >= this between two surfaced cards => same story mirrored across sites; keep
# only the higher-scored one so one run never shows the same thing twice.
WITHIN_DEDUP_THRESHOLD = 0.92

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

    def shortlist(
        self,
        candidates: list[tuple[str, str, str]],
        prompt: str,
        profile: dict,
        k: int,
    ) -> list[tuple[str, str, str]]:
        """Pick the ``k`` candidates whose title+snippet best match the query.

        Run BEFORE scraping so the slow fetch is spent only on the most
        promising URLs rather than the first N we happened to find.
        ``candidates`` are ``(title, url, snippet)`` tuples.
        """
        if k <= 0:
            return []
        if len(candidates) <= k:
            return candidates  # nothing to trim — skip the embed call entirely

        query_text = _profile_text(prompt, profile)
        cand_texts = [f"{title} {snippet}".strip() for title, _, snippet in candidates]
        vecs = self._embed([query_text] + cand_texts)
        query_vec = vecs[0]
        scored = sorted(
            zip(candidates, vecs[1:]),
            key=lambda cv: _dot(cv[1], query_vec),
            reverse=True,
        )
        return [cand for cand, _ in scored[:k]]

    def rank(
        self,
        cards: list[TopicCard],
        prompt: str,
        profile: dict,
        learned_titles: list[str],
        source_scores: dict[str, float] | None = None,
        tag_scores: dict[str, float] | None = None,
        min_score: float = 0.0,
        dedup_threshold: float | None = None,
    ) -> list[TopicCard]:
        """Return cards sorted by relevance, deduped against learned topics.

        ``source_scores`` / ``tag_scores`` are per-host / per-tag preferences in
        [-1, 1] learned from user feedback; they apply a small boost/penalty so
        ranking adapts over time without overriding semantic relevance.
        ``min_score`` drops cards whose final score falls below it (off-topic).
        ``dedup_threshold`` (when set) collapses near-identical cards within the
        result, keeping the highest-scored of each near-duplicate group.
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

        scored: list[tuple[TopicCard, list[float]]] = []
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

            if score < min_score:
                continue  # below the relevance floor — off-topic, drop it

            card.relevance_score = round(score, 4)
            scored.append((card, cvec))

        scored.sort(key=lambda cs: cs[0].relevance_score, reverse=True)
        if dedup_threshold is None:
            return [card for card, _ in scored]

        # Collapse near-identical cards (same story mirrored across sites):
        # keep the highest-scored, drop later near-duplicates.
        ranked: list[TopicCard] = []
        kept_vecs: list[list[float]] = []
        for card, cvec in scored:
            if any(_dot(cvec, kv) >= dedup_threshold for kv in kept_vecs):
                continue
            ranked.append(card)
            kept_vecs.append(cvec)
        return ranked
