"""Free web search via DuckDuckGo (no API key)."""

from __future__ import annotations

from magpie.search.base import SearchResult


class DuckDuckGoSearch:
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        from ddgs import DDGS

        results: list[SearchResult] = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(
                    SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    )
                )
        return results
