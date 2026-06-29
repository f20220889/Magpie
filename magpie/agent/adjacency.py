"""Suggest the *next* logical topics to learn, given the user's KB.

Looks at the user's domains/skills and what they've recently learned, then
proposes adjacent frontier topics — things one step beyond what they know,
not basics they already have. Pure LLM reasoning; no web access.
"""

from __future__ import annotations

from magpie.llm.base import LLMClient
from magpie.llm.factory import get_llm

_SYSTEM = (
    "You are a learning-path advisor for an IT professional. Given the reader's "
    "skills and the topics they've recently learned, propose the NEXT logical "
    "topics to explore — adjacent, slightly more advanced frontiers that build on "
    "what they know. Do NOT suggest things they already know or generic basics. "
    "Each suggestion needs a short, concrete reason tied to their profile. "
    'Respond ONLY with JSON: {"suggestions": [{"topic": "...", "reason": "..."}]}'
)


class AdjacencySuggester:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm()

    def suggest(
        self, profile: dict, learned_titles: list[str], n: int = 5
    ) -> list[dict]:
        """Return up to n {topic, reason} dicts for what to learn next."""
        skills = ", ".join(
            s for d in profile.get("domains", []) for s in d.get("skills", [])
        ) or "(general IT)"
        domains = ", ".join(d.get("name", "") for d in profile.get("domains", [])) or "(none)"
        learned = ", ".join(learned_titles) or "(nothing yet)"

        user = (
            f"Reader's domains: {domains}\n"
            f"Reader's skills: {skills}\n"
            f"Recently learned: {learned}\n\n"
            f"Propose up to {n} next topics as JSON."
        )
        data = self.llm.complete_json(user, system=_SYSTEM)
        raw = data.get("suggestions", []) if isinstance(data, dict) else []

        out: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic", "")).strip()
            if not topic or topic.lower() in seen:
                continue
            seen.add(topic.lower())
            out.append({"topic": topic, "reason": str(item.get("reason", "")).strip()})
        return out[:n]
