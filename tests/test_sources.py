"""Multi-source aggregation + connector parsing (HTTP mocked via monkeypatch)."""

import magpie.search.arxiv as arxiv_mod
import magpie.search.github as gh_mod
import magpie.search.hackernews as hn_mod
from magpie.search.arxiv import ArxivSearch
from magpie.search.base import MultiSource, SearchResult
from magpie.search.github import GitHubSearch
from magpie.search.hackernews import HackerNewsSearch


def test_multisource_dedupes_and_caps():
    class A:
        def search(self, q, max_results=8):
            return [SearchResult("a", "http://x", ""), SearchResult("b", "http://y", "")]

    class B:
        def search(self, q, max_results=8):
            return [SearchResult("b2", "http://y", ""), SearchResult("c", "http://z", "")]

    class Boom:
        def search(self, q, max_results=8):
            raise RuntimeError("down")  # must not break the run

    merged = MultiSource([A(), Boom(), B()]).search("q", max_results=10)
    assert [r.url for r in merged] == ["http://x", "http://y", "http://z"]


def test_hackernews_parses(monkeypatch, fake_resp):
    payload = {"hits": [
        {"title": "Cool", "url": "http://cool", "points": 42, "objectID": "1"},
        {"title": "Ask HN", "url": None, "objectID": "99", "points": 5},
    ]}
    monkeypatch.setattr(hn_mod.httpx, "get", lambda *a, **k: fake_resp(json_data=payload))
    out = HackerNewsSearch().search("x")
    assert out[0].url == "http://cool"
    assert out[1].url == "https://news.ycombinator.com/item?id=99"  # fallback


def test_github_parses(monkeypatch, fake_resp):
    payload = {"items": [
        {"full_name": "org/repo", "html_url": "http://gh/repo", "description": "d"},
        {"full_name": "no/url", "html_url": "", "description": "skip"},
    ]}
    monkeypatch.setattr(gh_mod.httpx, "get", lambda *a, **k: fake_resp(json_data=payload))
    out = GitHubSearch().search("x")
    assert [r.url for r in out] == ["http://gh/repo"]  # empty-url dropped


def test_arxiv_parses(monkeypatch, fake_resp):
    xml = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Paper One</title><id>http://arxiv/1</id>
        <summary>abstract here</summary></entry>
    </feed>"""
    monkeypatch.setattr(arxiv_mod.httpx, "get", lambda *a, **k: fake_resp(text=xml))
    out = ArxivSearch().search("x")
    assert out[0].title == "Paper One"
    assert out[0].url == "http://arxiv/1"


def test_source_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise hn_mod.httpx.ConnectError("nope")

    monkeypatch.setattr(hn_mod.httpx, "get", boom)
    assert HackerNewsSearch().search("x") == []
