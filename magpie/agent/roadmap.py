"""Build an ordered learning roadmap from the user's KB.

Where the adjacency suggester proposes a flat set of next topics, the roadmap
orders them into a sequence — each step building on the previous — so the user
has a path, not just a pile. Pure LLM reasoning; no web access.
"""

from __future__ import annotations

from magpie.llm.base import LLMClient
from magpie.llm.factory import get_llm

_SYSTEM = (
    "You are a learning-path planner for an IT professional. Given the reader's "
    "skills and what they've learned, design an ORDERED roadmap of topics to learn "
    "next — each step building on the previous, progressing from where they are to "
    "a meaningful goal. Skip things they already know. Keep it concrete. "
    'Respond ONLY with JSON: {"roadmap": [{"topic": "...", "reason": "..."}]} '
    "where array order IS the learning order."
)


class RoadmapBuilder:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm()

    def build(self, profile: dict, learned_titles: list[str], n: int = 6) -> list[dict]:
        """Return an ordered list of {step, topic, reason}."""
        skills = ", ".join(
            s for d in profile.get("domains", []) for s in d.get("skills", [])
        ) or "(general IT)"
        domains = ", ".join(d.get("name", "") for d in profile.get("domains", [])) or "(none)"
        learned = ", ".join(learned_titles) or "(nothing yet)"

        user = (
            f"Reader's domains: {domains}\n"
            f"Reader's skills: {skills}\n"
            f"Already learned: {learned}\n\n"
            f"Design an ordered roadmap of up to {n} steps as JSON."
        )
        data = self.llm.complete_json(user, system=_SYSTEM)
        raw = data.get("roadmap", []) if isinstance(data, dict) else []

        out: list[dict] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            topic = str(item.get("topic", "")).strip()
            if not topic or topic.lower() in seen:
                continue
            seen.add(topic.lower())
            out.append({
                "step": len(out) + 1,
                "topic": topic,
                "reason": str(item.get("reason", "")).strip(),
            })
            if len(out) >= n:
                break
        return out
