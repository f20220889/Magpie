"""Free search via a self-hosted SearXNG instance (JSON API).

Requires a running SearXNG with the JSON format enabled; set SEARXNG_URL.
Self-hosted = still free and private.
"""

from __future__ import annotations

import httpx

from magpie.config import settings
from magpie.search.base import SearchResult


class SearxngSearch:
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        try:
            resp = httpx.get(
                f"{settings.searxng_url.rstrip('/')}/search",
                params={"q": query, "format": "json"},
                timeout=settings.scrape_timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            items = resp.json().get("results", [])
        except (httpx.HTTPError, ValueError):
            return []
        results: list[SearchResult] = []
        for it in items[:max_results]:
            url = it.get("url", "")
            if url:
                results.append(
                    SearchResult(
                        title=it.get("title") or url,
                        url=url,
                        snippet=(it.get("content") or "")[:200],
                    )
                )
        return results
