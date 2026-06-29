"""Expand a user prompt into targeted search queries.

Biases queries toward the user's domains/skills and AWAY from topics
already in the knowledge base (so results stay fresh and non-redundant).
"""

from __future__ import annotations

from magpie.llm.base import LLMClient
from magpie.llm.factory import get_llm

_SYSTEM = (
    "You are a search-query planner for a personal tech-learning assistant. "
    "Given a user's intent and their skill profile, produce focused web-search "
    "queries that surface NEW, recent, relevant technologies. Prefer specific, "
    "high-signal queries over broad ones. Avoid topics the user already knows. "
    "Respond ONLY with JSON of the form {\"queries\": [\"...\", \"...\"]}."
)


class QueryPlanner:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm()

    def plan(
        self, prompt: str, profile: dict, learned_titles: list[str], n: int = 5
    ) -> list[str]:
        """Return a list of search queries to run."""
        domains = ", ".join(
            f"{d['name']} ({', '.join(d['skills'])})" if d["skills"] else d["name"]
            for d in profile.get("domains", [])
        ) or "(none given)"
        known = ", ".join(learned_titles) or "(none yet)"

        user = (
            f"User intent: {prompt}\n\n"
            f"User's domains & skills: {domains}\n"
            f"Topics the user ALREADY knows (do not repeat these): {known}\n\n"
            f"Produce up to {n} search queries as JSON."
        )
        data = self.llm.complete_json(user, system=_SYSTEM)
        queries = data.get("queries", []) if isinstance(data, dict) else []
        # Normalize: strings only, stripped, deduped, capped.
        seen: set[str] = set()
        out: list[str] = []
        for q in queries:
            if not isinstance(q, str):
                continue
            q = q.strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                out.append(q)
        return out[:n] or [prompt]  # fall back to the raw prompt if model gives nothing
