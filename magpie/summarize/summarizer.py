"""Condense extracted content into a Topic Card using the local LLM."""

from __future__ import annotations

from magpie.knowledge.models import TopicCard
from magpie.llm.base import LLMClient
from magpie.llm.factory import get_llm

_SYSTEM = (
    "You are a tech-learning summarizer. Given an article and the reader's skill "
    "profile, produce a concise Topic Card. Be accurate and grounded ONLY in the "
    "article text — never invent facts. Frame 'why_relevant' in terms of the "
    "reader's existing skills. Respond ONLY with JSON of the form: "
    '{"title": "...", "overview": "2-4 sentence summary", '
    '"why_relevant": "1-2 sentences tying it to the reader\'s skills", '
    '"tags": ["...", "..."]}'
)

# Cap content fed to the model to keep prompts fast on local hardware.
_MAX_CHARS = 6000


class Summarizer:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or get_llm()

    def to_card(self, content: str, source_url: str, profile: dict) -> TopicCard:
        """Summarize content into a Topic Card framed by the user's profile."""
        skills = ", ".join(
            s for d in profile.get("domains", []) for s in d["skills"]
        ) or "(general IT)"

        user = (
            f"Reader's skills: {skills}\n\n"
            f"Article (source: {source_url}):\n"
            f"\"\"\"\n{content[:_MAX_CHARS]}\n\"\"\"\n\n"
            "Produce the Topic Card JSON."
        )
        data = self.llm.complete_json(user, system=_SYSTEM)
        if not isinstance(data, dict):
            data = {}

        tags = data.get("tags", [])
        tags = [t for t in tags if isinstance(t, str)] if isinstance(tags, list) else []

        return TopicCard(
            title=str(data.get("title") or source_url),
            overview=str(data.get("overview") or ""),
            why_relevant=str(data.get("why_relevant") or ""),
            links=[source_url],
            tags=tags,
            source_url=source_url,
        )
