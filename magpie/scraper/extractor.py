"""Fetch a URL and extract clean main-content text, with an on-disk cache.

Scraping is the slow part of a run and the same URL often resurfaces across
prompts/sources, so successful extractions are cached under ``cache_dir`` keyed
by URL hash. Set ``cache_ttl_hours=0`` to disable.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import httpx

from magpie.config import settings


def _cache_path(url: str) -> Path:
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return Path(settings.cache_dir) / f"{key}.txt"


def _read_cache(url: str) -> str | None:
    if settings.cache_ttl_hours <= 0:
        return None
    path = _cache_path(url)
    if not path.exists():
        return None
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > settings.cache_ttl_hours:
        return None
    text = path.read_text(encoding="utf-8")
    return text or None


def _write_cache(url: str, text: str) -> None:
    if settings.cache_ttl_hours <= 0:
        return
    path = _cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# Content types we can extract article text from; anything else (pdf, image,
# json, octet-stream) is skipped before it reaches the extractor.
_TEXTUAL = ("html", "xml", "text")


def _is_textual(resp: httpx.Response) -> bool:
    ctype = (getattr(resp, "headers", None) or {}).get("content-type", "")
    ctype = ctype.lower()
    if not ctype:
        return True  # unknown — let the extractor decide
    return any(t in ctype for t in _TEXTUAL)


def fetch_and_extract(url: str) -> str | None:
    """Return cleaned readable article text for a URL, or None if unusable.

    Sends a realistic browser User-Agent (many sites bot-wall default clients),
    skips non-textual payloads, and rejects extractions too short to be real
    content so junk pages never become inaccurate cards. Successful extractions
    are cached; cache hits skip the network entirely.
    """
    cached = _read_cache(url)
    if cached is not None:
        return cached

    import trafilatura

    headers = {
        "User-Agent": settings.scrape_user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = httpx.get(
            url,
            timeout=settings.scrape_timeout,
            follow_redirects=True,
            headers=headers,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None

    if not _is_textual(resp):
        return None

    text = trafilatura.extract(
        resp.text,
        include_comments=False,
        include_tables=False,
        favor_precision=True,  # prefer clean main-content over noisy recall
        deduplicate=True,      # drop repeated boilerplate blocks
    )
    # Too-short extractions are bot-walls or nav chrome, not article content.
    if not text or len(text.strip()) < settings.min_content_chars:
        return None

    _write_cache(url, text)
    return text
