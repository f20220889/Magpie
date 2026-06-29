#!/usr/bin/env python
"""End-to-end Magpie demo against the real (free/local) pipeline.

Runs in an isolated demo DB so it never touches your real hoard. Needs Ollama
running; hits the network for one small discovery. Run:

    .venv/bin/python scripts/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script (no install needed).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from magpie import exporter  # noqa: E402
from magpie.agent.orchestrator import Orchestrator  # noqa: E402
from magpie.agent.roadmap import RoadmapBuilder  # noqa: E402
from magpie.knowledge.store import KnowledgeStore  # noqa: E402
from magpie.llm.ollama_client import OllamaClient, OllamaError  # noqa: E402

DEMO_DB = "data/demo.db"


def hr(title: str) -> None:
    print(f"\n{'─' * 4} {title} {'─' * (60 - len(title))}")


def main() -> int:
    # 0. Preflight: Ollama must be up.
    try:
        OllamaClient().health()
    except OllamaError as e:
        print(f"✗ {e}\n  Start Ollama (`ollama serve`) and pull a model, then retry.")
        return 1

    Path(DEMO_DB).unlink(missing_ok=True)
    base = KnowledgeStore(db_path=DEMO_DB)
    base.init_db()
    uid = base.create_user(email="demo@magpie.local", display_name="Demo")
    store = base.for_user(uid)

    hr("1. Seed a demo profile")
    backend = store.add_domain("Backend", weight=2.0)
    store.add_skill(backend, "Python", 4)
    store.add_skill(backend, "PostgreSQL", 3)
    store.add_learned_topic("REST APIs", "(seeded)")
    print("Domains/skills: Backend → Python, PostgreSQL | learned: REST APIs")

    hr("2. Discover (real search + scrape + local LLM)")
    orch = Orchestrator(store=store)
    cards = orch.run(
        "what's new in Python web framework performance 2026",
        progress=lambda stage, msg: print(f"  · {stage}: {msg}"),
    )[:2]
    if not cards:
        print("No cards found (network/model hiccup). Try again.")
        return 1
    for i, c in enumerate(cards, 1):
        print(f"\n[{i}] {c.title}  (relevance {c.relevance_score:.2f})")
        print(f"    {c.overview[:160]}")
        print(f"    why: {c.why_relevant[:160]}")

    hr("3. Learn the top card (closes the loop)")
    orch.commit_learned(cards[0])
    print(f"✓ Learned: {cards[0].title}")
    print("Hoard now:", store.learned_titles())

    hr("4. Roadmap — what to learn next, in order")
    steps = RoadmapBuilder().build(store.profile(), store.learned_titles(), n=4)
    for s in steps:
        print(f"  {s['step']}. {s['topic']}")

    hr("5. Export hoard → Markdown")
    topics = [t.model_dump(mode="json") for t in store.list_learned()]
    print(exporter.to_markdown(topics))

    Path(DEMO_DB).unlink(missing_ok=True)
    print("\n✓ Demo complete (demo DB cleaned up).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
