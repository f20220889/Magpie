"""Export the learned-topics hoard to portable formats.

Pure functions over a list of learned-topic dicts (as returned by the store /
API), so they're trivial to test and reuse from CLI and web.
"""

from __future__ import annotations

import json

FORMATS = ("md", "json", "anki")
MIME = {"md": "text/markdown", "json": "application/json", "anki": "text/tab-separated-values"}
EXT = {"md": "md", "json": "json", "anki": "tsv"}


def _tags(topic: dict) -> list[str]:
    return [t for t in (topic.get("tags") or []) if isinstance(t, str)]


def to_json(topics: list[dict]) -> str:
    return json.dumps(topics, indent=2, ensure_ascii=False)


def to_markdown(topics: list[dict]) -> str:
    """Obsidian-friendly markdown: one section per topic, #tags inline."""
    lines = ["# Magpie — Learned Topics", ""]
    for t in topics:
        lines.append(f"## {t.get('title', 'Untitled')}")
        if t.get("summary"):
            lines.append("")
            lines.append(t["summary"])
        if t.get("source_url"):
            lines.append("")
            lines.append(f"Source: <{t['source_url']}>")
        tags = _tags(t)
        if tags:
            lines.append("")
            lines.append(" ".join(f"#{tag.replace(' ', '-')}" for tag in tags))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _anki_escape(s: str) -> str:
    # TSV: strip tabs/newlines that would break the row.
    return (s or "").replace("\t", " ").replace("\n", " ").strip()


def to_anki_tsv(topics: list[dict]) -> str:
    """Tab-separated front/back/tags, importable into Anki (Notes in Plain Text)."""
    rows = []
    for t in topics:
        front = _anki_escape(t.get("title", ""))
        back_parts = [_anki_escape(t.get("summary", ""))]
        if t.get("source_url"):
            back_parts.append(f"Source: {t['source_url']}")
        back = " — ".join(p for p in back_parts if p)
        tags = " ".join(tag.replace(" ", "-") for tag in _tags(t))
        rows.append(f"{front}\t{back}\t{tags}")
    return "\n".join(rows) + ("\n" if rows else "")


def export(topics: list[dict], fmt: str) -> str:
    if fmt == "json":
        return to_json(topics)
    if fmt == "md":
        return to_markdown(topics)
    if fmt == "anki":
        return to_anki_tsv(topics)
    raise ValueError(f"Unknown export format: {fmt}. Use one of {FORMATS}.")
