"""Scrape cache behavior + SearXNG connector parsing."""

import magpie.scraper.extractor as ex
import magpie.search.searxng as sx
from magpie.search.searxng import SearxngSearch


def test_cache_hit_skips_network(tmp_path, monkeypatch, fake_resp):
    monkeypatch.setattr(ex.settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(ex.settings, "cache_ttl_hours", 168)

    calls = {"n": 0}

    def fake_get(url, **k):
        calls["n"] += 1
        return fake_resp(text="<html><body>" + "hello world " * 30 + "</body></html>")

    monkeypatch.setattr(ex.httpx, "get", fake_get)

    first = ex.fetch_and_extract("http://example.com/a")
    second = ex.fetch_and_extract("http://example.com/a")  # served from cache
    assert first and first == second
    assert calls["n"] == 1  # network hit only once


def test_cache_disabled_when_ttl_zero(tmp_path, monkeypatch, fake_resp):
    monkeypatch.setattr(ex.settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(ex.settings, "cache_ttl_hours", 0)
    calls = {"n": 0}

    def fake_get(url, **k):
        calls["n"] += 1
        return fake_resp(text="<html><body>" + "fresh content " * 30 + "</body></html>")

    monkeypatch.setattr(ex.httpx, "get", fake_get)
    ex.fetch_and_extract("http://example.com/b")
    ex.fetch_and_extract("http://example.com/b")
    assert calls["n"] == 2  # no caching -> fetched twice


def test_failed_fetch_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(ex.settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(ex.settings, "cache_ttl_hours", 168)

    def boom(url, **k):
        raise ex.httpx.ConnectError("down")

    monkeypatch.setattr(ex.httpx, "get", boom)
    assert ex.fetch_and_extract("http://example.com/c") is None
    assert not list(tmp_path.glob("*.txt"))  # nothing cached


def test_short_extraction_dropped_and_not_cached(tmp_path, monkeypatch, fake_resp):
    """A bot-wall / nav-only page extracts too little to be real content."""
    monkeypatch.setattr(ex.settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(ex.settings, "cache_ttl_hours", 168)
    monkeypatch.setattr(ex.settings, "min_content_chars", 250)
    monkeypatch.setattr(
        ex.httpx, "get",
        lambda url, **k: fake_resp(text="<html><body>Just a tiny stub.</body></html>"),
    )
    assert ex.fetch_and_extract("http://example.com/thin") is None
    assert not list(tmp_path.glob("*.txt"))  # junk never cached


def test_non_textual_content_type_skipped(tmp_path, monkeypatch, fake_resp):
    monkeypatch.setattr(ex.settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(ex.settings, "cache_ttl_hours", 168)

    def fake_get(url, **k):
        r = fake_resp(text="%PDF-1.7 binary…")
        r.headers = {"content-type": "application/pdf"}
        return r

    monkeypatch.setattr(ex.httpx, "get", fake_get)
    assert ex.fetch_and_extract("http://example.com/paper.pdf") is None


def test_browser_user_agent_is_sent(tmp_path, monkeypatch, fake_resp):
    monkeypatch.setattr(ex.settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(ex.settings, "cache_ttl_hours", 0)
    seen = {}

    def fake_get(url, **k):
        seen.update(k.get("headers") or {})
        return fake_resp(text="<html><body>" + "real article text " * 30 + "</body></html>")

    monkeypatch.setattr(ex.httpx, "get", fake_get)
    ex.fetch_and_extract("http://example.com/a")
    assert "Mozilla/5.0" in seen.get("User-Agent", "")  # not python-httpx default


def test_searxng_parses(monkeypatch, fake_resp):
    payload = {"results": [
        {"title": "R1", "url": "http://r1", "content": "snippet"},
        {"title": "no url", "url": "", "content": "skip"},
    ]}
    monkeypatch.setattr(sx.httpx, "get", lambda *a, **k: fake_resp(json_data=payload))
    out = SearxngSearch().search("x")
    assert [r.url for r in out] == ["http://r1"]
