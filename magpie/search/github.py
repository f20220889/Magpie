"""Free, keyless search over GitHub repositories (unauthenticated API).

Unauthenticated requests are rate-limited (~10/min for search); failures are
swallowed so one throttled source never breaks a discovery run.
"""

from __future__ import annotations

import httpx

from magpie.config import settings
from magpie.search.base import SearchResult

_API = "https://api.github.com/search/repositories"


class GitHubSearch:
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        try:
            resp = httpx.get(
                _API,
                params={"q": query, "sort": "stars", "order": "desc",
                        "per_page": max_results},
                headers={"Accept": "application/vnd.github+json"},
                timeout=settings.scrape_timeout,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except (httpx.HTTPError, ValueError):
            return []
        results: list[SearchResult] = []
        for it in items:
            results.append(
                SearchResult(
                    title=it.get("full_name") or it.get("name") or "",
                    url=it.get("html_url", ""),
                    snippet=(it.get("description") or "")[:200],
                )
            )
        return [r for r in results if r.url]
