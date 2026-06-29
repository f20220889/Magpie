"""Magpie command-line interface."""

from __future__ import annotations

import os

import typer
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from magpie.knowledge.store import KnowledgeStore

app = typer.Typer(help="Magpie — forage the web for tech relevant to what you know.")
console = Console()

# Default web-UI port. Overridable via MAGPIE_PORT (chosen to avoid the common 8000).
DEFAULT_PORT = int(os.getenv("MAGPIE_PORT", "8077"))


def _split(raw: str) -> list[str]:
    """Split a comma-separated answer into clean, non-empty items."""
    return [p.strip() for p in raw.split(",") if p.strip()]


# The CLI operates as a single local account (the machine owner). Web users are
# separate; the data store is user-scoped, so the CLI binds to this local user.
_LOCAL_EMAIL = os.getenv("MAGPIE_LOCAL_USER", "local@magpie.local")


def _local_store() -> KnowledgeStore:
    """Return a store bound to the local CLI user, creating it if needed."""
    store = KnowledgeStore()
    store.init_db()
    user = store.get_user_by_email(_LOCAL_EMAIL)
    uid = user["id"] if user else store.create_user(
        email=_LOCAL_EMAIL, display_name="Local user"
    )
    return store.for_user(uid)


@app.command()
def init() -> None:
    """Onboard: capture your domains, skills, and known topics into the KB."""
    store = _local_store()

    console.print("[bold cyan]🐦 Magpie onboarding[/]\n")
    console.print(
        "Tell Magpie what you work in so it can forage tech relevant to [bold]you[/].\n"
        "Enter comma-separated values. Press Enter to skip an optional step.\n"
    )

    domains_raw = Prompt.ask("[bold]Primary domains[/] (e.g. Backend, DevOps, ML)")
    domains = _split(domains_raw)
    if not domains:
        console.print("[yellow]No domains entered — nothing to save.[/]")
        raise typer.Exit(code=1)

    domain_ids: dict[str, int] = {}
    for name in domains:
        domain_ids[name] = store.add_domain(name)

    # Per-domain skills
    for name in domains:
        skills_raw = Prompt.ask(
            f"[bold]Key skills[/] under [cyan]{name}[/] (e.g. Python, Kubernetes)",
            default="",
        )
        for skill in _split(skills_raw):
            store.add_skill(domain_ids[name], skill)

    # Optional already-known topics -> seed the learned set for dedup
    known_raw = Prompt.ask(
        "[bold]Topics you already know well[/] (optional)", default=""
    )
    for topic in _split(known_raw):
        store.add_learned_topic(title=topic, summary="(seeded at onboarding)")

    console.print("\n[green]✓ Saved.[/] Your starting profile:\n")
    _print_profile(store)
    console.print(
        '\nRun a discovery with: [bold]magpie discover "what\'s new in <topic>"[/]'
    )


@app.command()
def discover(
    prompt: str,
    top: int = typer.Option(5, help="How many top-ranked cards to review."),
) -> None:
    """Run a discovery: search, scrape, summarize, rank, then learn/skip each card."""
    from rich.panel import Panel
    from rich.status import Status

    from magpie.agent.orchestrator import Orchestrator

    orch = Orchestrator(store=_local_store())
    status = Status("Starting…", console=console)
    status.start()

    def progress(stage: str, message: str) -> None:
        status.update(f"[cyan]{stage}[/] · {message}")

    try:
        cards = orch.run(prompt, progress=progress)
    finally:
        status.stop()

    if not cards:
        console.print("[yellow]No relevant new topics found. Try a different prompt.[/]")
        return

    cards = cards[:top]
    console.print(f"\n[bold]Top {len(cards)} for:[/] {prompt}\n")

    for i, card in enumerate(cards, 1):
        links = "\n".join(f"  • {u}" for u in card.links)
        tags = f"[dim]{', '.join(card.tags)}[/]" if card.tags else ""
        body = (
            f"[bold]{card.overview}[/]\n\n"
            f"[green]Why relevant:[/] {card.why_relevant}\n\n"
            f"[bold]Read more:[/]\n{links}\n"
            f"{tags}"
        )
        console.print(
            Panel(
                body,
                title=f"[{i}] {card.title}",
                subtitle=f"relevance {card.relevance_score:.2f}",
                border_style="cyan",
            )
        )
        choice = Prompt.ask(
            "Add to knowledge?", choices=["learn", "skip", "quit"], default="skip"
        )
        if choice == "quit":
            break
        if choice == "learn":
            orch.commit_learned(card)
            console.print("[green]✓ Learned[/] — future runs will build on this.\n")
        else:
            console.print("[dim]skipped[/]\n")

    console.print("[bold cyan]Done.[/] Run [bold]magpie learned[/] to review your hoard.")


@app.command()
def serve(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    """Launch the local Magpie web UI."""
    import uvicorn

    console.print(f"[bold cyan]🐦 Magpie[/] UI at [bold]http://{host}:{port}[/]")
    uvicorn.run("magpie.web.server:app", host=host, port=port, reload=False)


@app.command()
def doctor() -> None:
    """Check that the configured LLM provider is reachable and a model resolves."""
    from magpie.config import settings
    from magpie.llm.base import LLMError
    from magpie.llm.factory import get_llm

    client = get_llm()
    try:
        h = client.health()
    except LLMError as e:
        console.print(f"[red]✗ {e}[/]")
        raise typer.Exit(code=1)
    console.print(f"[green]✓ LLM reachable[/] at {h['host']}")
    console.print(f"  provider: [cyan]{settings.llm_provider}[/] · resolved model: "
                  f"[bold]{h['resolved_model']}[/]")
    console.print(f"  available: {', '.join(h['available'][:8])}")


@app.command()
def profile() -> None:
    """Show your current domains, skills, and learned topics."""
    _print_profile(_local_store())


@app.command()
def learned() -> None:
    """List topics you've committed to your knowledge base."""
    store = _local_store()
    topics = store.list_learned()
    if not topics:
        console.print("[yellow]No learned topics yet.[/]")
        return
    for t in topics:
        tags = f" [dim]{', '.join(t.tags)}[/]" if t.tags else ""
        console.print(f"• [bold]{t.title}[/]{tags}")


@app.command()
def suggest(n: int = 5) -> None:
    """Suggest the next logical topics to learn, based on your KB."""
    from magpie.agent.adjacency import AdjacencySuggester

    store = _local_store()
    with console.status("thinking about what's next…"):
        items = AdjacencySuggester().suggest(store.profile(), store.learned_titles(), n)
    if not items:
        console.print("[yellow]No suggestions — add some skills/learned topics first.[/]")
        return
    console.print("[bold cyan]What to learn next:[/]\n")
    for s in items:
        console.print(f"[bold]→ {s['topic']}[/]")
        if s["reason"]:
            console.print(f"  [dim]{s['reason']}[/]")
    console.print('\nForage one with: [bold]magpie discover "<topic>"[/]')


@app.command()
def roadmap(n: int = 6) -> None:
    """Generate an ordered learning roadmap from your knowledge base."""
    from magpie.agent.roadmap import RoadmapBuilder

    store = _local_store()
    with console.status("planning your path…"):
        steps = RoadmapBuilder().build(store.profile(), store.learned_titles(), n)
    if not steps:
        console.print("[yellow]No roadmap — add skills/learned topics first.[/]")
        return
    console.print("[bold cyan]Your learning roadmap:[/]\n")
    for s in steps:
        console.print(f"[bold]{s['step']}. {s['topic']}[/]")
        if s["reason"]:
            console.print(f"   [dim]{s['reason']}[/]")


@app.command()
def export(fmt: str = "md", out: str = "") -> None:
    """Export your learned topics. fmt: md | json | anki."""
    from pathlib import Path

    from magpie import exporter

    store = _local_store()
    topics = [t.model_dump(mode="json") for t in store.list_learned(limit=10000)]
    try:
        content = exporter.export(topics, fmt)
    except ValueError as e:
        console.print(f"[red]{e}[/]")
        raise typer.Exit(code=1)
    if out:
        Path(out).write_text(content, encoding="utf-8")
        console.print(f"[green]✓ Exported[/] {len(topics)} topics → {out}")
    else:
        console.print(content)


@app.command()
def digest(prompts: int = 3, per_prompt: int = 3) -> None:
    """Auto-run discoveries seeded from your next-topic suggestions (for scheduling)."""
    from magpie.agent.digest import DigestRunner

    runner = DigestRunner(store=_local_store())
    status = console.status("starting digest…")
    status.start()

    def progress(stage: str, message: str) -> None:
        status.update(f"[cyan]{stage}[/] · {message}")

    try:
        result = runner.run(prompts, per_prompt, progress=progress)
    finally:
        status.stop()

    console.print(f"[bold cyan]🐦 Digest[/] — explored: {', '.join(result['prompts'])}\n")
    if not result["cards"]:
        console.print("[yellow]No new cards this run.[/]")
        return
    for c in result["cards"]:
        console.print(f"[bold]{c.title}[/] [dim](relevance {c.relevance_score:.2f})[/]")
        if c.source_url:
            console.print(f"  {c.source_url}")
    console.print(
        f"\n[green]{len(result['cards'])} cards saved.[/] "
        "Review in the web UI History, or run [bold]magpie learned[/]."
    )


@app.command()
def forget(title: str) -> None:
    """Remove a learned topic from your knowledge base (by title)."""
    store = _local_store()
    n = store.forget_topic_by_title(title)
    if n:
        console.print(f"[green]✓ Forgot[/] {n} topic(s) matching '{title}'.")
    else:
        console.print(f"[yellow]No learned topic matched '{title}'.[/]")


def _print_profile(store: KnowledgeStore) -> None:
    prof = store.profile()
    if not prof["domains"]:
        console.print("[yellow]No profile yet — run [bold]magpie init[/].[/]")
        return
    table = Table(title="Magpie profile")
    table.add_column("Domain", style="cyan")
    table.add_column("Weight", justify="right")
    table.add_column("Skills")
    for d in prof["domains"]:
        table.add_row(d["name"], f"{d['weight']:.1f}", ", ".join(d["skills"]) or "—")
    console.print(table)
    if prof["learned"]:
        console.print(f"\n[bold]Learned topics:[/] {', '.join(prof['learned'])}")


if __name__ == "__main__":
    app()
