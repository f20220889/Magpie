"""Shared test fixtures — fakes reused across the suite (no real LLM/HTTP)."""

import pytest


class _FakeLLM:
    """Stands in for OllamaClient: returns a canned JSON payload."""

    def __init__(self, payload):
        self._payload = payload

    def complete_json(self, prompt, system=None):
        return self._payload


class _FakeResp:
    """Stands in for an httpx.Response."""

    def __init__(self, *, json_data=None, text=""):
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return self._json


@pytest.fixture
def make_llm():
    """Factory: make_llm(payload) -> fake LLM whose complete_json returns payload."""
    return _FakeLLM


@pytest.fixture
def fake_resp():
    """Factory: fake_resp(json_data=..., text=...) -> fake httpx response."""
    return _FakeResp
