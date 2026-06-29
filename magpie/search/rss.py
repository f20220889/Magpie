"""Optional RSS/Atom connector. Reads feed URLs from MAGPIE config (rss_feeds).

Loosely filters feed items by query words so it slots into the same pipeline.
Only active when 'rss' is in search_sources AND rss_feeds is set.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from magpie.config import settings
from magpie.search.base import SearchResult

_ATOM = "{http://www.w3.org/2005/Atom}"


def _feeds() -> list[str]:
    return [u.strip() for u in settings.rss_feeds.split(",") if u.strip()]


class RssSearch:
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        words = {w.lower() for w in query.split() if len(w) > 2}
        out: list[SearchResult] = []
        for feed in _feeds():
            out.extend(self._read(feed, words))
        return out[:max_results]

    def _read(self, feed: str, words: set[str]) -> list[SearchResult]:
        try:
            resp = httpx.get(feed, timeout=settings.scrape_timeout, follow_redirects=True)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except (httpx.HTTPError, ET.ParseError):
            return []
        items: list[SearchResult] = []
        # RSS 2.0 <item> and Atom <entry>
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if tag not in {"item", "entry"}:
                continue
            title = (el.findtext("title") or el.findtext(f"{_ATOM}title") or "").strip()
            link = el.findtext("link") or ""
            if not link:  # Atom uses <link href="">
                a = el.find(f"{_ATOM}link")
                link = a.get("href") if a is not None else ""
            desc = (el.findtext("description") or el.findtext(f"{_ATOM}summary") or "").strip()
            hay = f"{title} {desc}".lower()
            if not link or (words and not any(w in hay for w in words)):
                continue
            items.append(SearchResult(title=title or link, url=link, snippet=desc[:200]))
        return items
