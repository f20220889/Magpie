"""Free, keyless search over arXiv papers (Atom API)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from magpie.config import settings
from magpie.search.base import SearchResult

_API = "http://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivSearch:
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        try:
            resp = httpx.get(
                _API,
                params={"search_query": f"all:{query}", "max_results": max_results,
                        "sortBy": "submittedDate", "sortOrder": "descending"},
                timeout=settings.scrape_timeout,
                follow_redirects=True,
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except (httpx.HTTPError, ET.ParseError):
            return []
        results: list[SearchResult] = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = (entry.findtext(f"{_ATOM}title") or "").strip().replace("\n", " ")
            url = (entry.findtext(f"{_ATOM}id") or "").strip()
            summary = (entry.findtext(f"{_ATOM}summary") or "").strip().replace("\n", " ")
            if url:
                results.append(SearchResult(title=title or url, url=url, snippet=summary[:200]))
        return results
