"""Free, keyless search over Hacker News stories (Algolia API)."""

from __future__ import annotations

import httpx

from magpie.config import settings
from magpie.search.base import SearchResult

_API = "https://hn.algolia.com/api/v1/search"


class HackerNewsSearch:
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        try:
            resp = httpx.get(
                _API,
                params={"query": query, "tags": "story", "hitsPerPage": max_results},
                timeout=settings.scrape_timeout,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except (httpx.HTTPError, ValueError):
            return []
        results: list[SearchResult] = []
        for h in hits:
            url = h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
            title = h.get("title") or h.get("story_title") or url
            results.append(SearchResult(title=title, url=url, snippet=f"HN · {h.get('points', 0)} points"))
        return results
