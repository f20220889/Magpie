"""Search provider interface + factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from magpie.config import settings


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]: ...


def _make_source(name: str) -> SearchProvider | None:
    if name == "duckduckgo":
        from magpie.search.duckduckgo import DuckDuckGoSearch
        return DuckDuckGoSearch()
    if name == "hackernews":
        from magpie.search.hackernews import HackerNewsSearch
        return HackerNewsSearch()
    if name == "arxiv":
        from magpie.search.arxiv import ArxivSearch
        return ArxivSearch()
    if name == "github":
        from magpie.search.github import GitHubSearch
        return GitHubSearch()
    if name == "rss":
        from magpie.search.rss import RssSearch
        return RssSearch()
    if name == "searxng":
        from magpie.search.searxng import SearxngSearch
        return SearxngSearch()
    return None  # unknown source name -> skipped


class MultiSource:
    """Fan a query out to several free sources and merge, deduped by URL.

    A failing source returns nothing rather than breaking the run, so adding
    sources only ever helps. Sources are queried round-robin-fair: each may
    contribute up to ``per_source`` results.
    """

    def __init__(self, sources: list[SearchProvider], per_source: int = 5) -> None:
        self.sources = sources
        self.per_source = per_source

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        seen: set[str] = set()
        merged: list[SearchResult] = []
        for src in self.sources:
            try:
                results = src.search(query, max_results=self.per_source)
            except Exception:
                continue
            for r in results:
                if r.url and r.url not in seen:
                    seen.add(r.url)
                    merged.append(r)
        return merged[:max_results]


def get_search_provider() -> SearchProvider:
    """Build the configured multi-source search provider (all free/keyless)."""
    sources = [s for name in settings.source_list if (s := _make_source(name))]
    if not sources:  # fall back to DuckDuckGo if config is empty/invalid
        from magpie.search.duckduckgo import DuckDuckGoSearch
        sources = [DuckDuckGoSearch()]
    return MultiSource(sources)
