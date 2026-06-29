"""LLM provider abstraction: factory selection, OpenAI-compat client, embeddings."""

from __future__ import annotations

import math

import pytest

import magpie.llm.openai_compat as oc
from magpie.config import settings
from magpie.llm.base import LLMError
from magpie.llm.factory import PROVIDERS, get_llm
from magpie.llm.openai_compat import OpenAICompatClient, _strip_fences


def test_factory_default_is_ollama(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    from magpie.llm.ollama_client import OllamaClient

    assert isinstance(get_llm(), OllamaClient)


def test_factory_builds_every_hosted_provider(monkeypatch):
    monkeypatch.setattr(settings, "llm_model", "")
    for name, preset in PROVIDERS.items():
        monkeypatch.setattr(settings, "llm_provider", name)
        client = get_llm()
        assert isinstance(client, OpenAICompatClient)
        assert client.base_url == preset.base_url.rstrip("/")
        assert client.model == preset.default_model


def test_factory_unknown_provider_raises(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "bogus")
    with pytest.raises(LLMError):
        get_llm()


def test_llm_model_override(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "llm_model", "my-custom-model")
    assert get_llm().model == "my-custom-model"


def test_strip_fences():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences("```\n[1,2]\n```") == "[1,2]"
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_openai_compat_parses_json_response(monkeypatch):
    client = OpenAICompatClient("https://x/v1", "key", "m", "groq", "GROQ_API_KEY")

    class _R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": '```json\n{"a": 1}\n```'}}]}

    monkeypatch.setattr(oc.httpx, "post", lambda *a, **k: _R())
    assert client.complete_json("hi") == {"a": 1}


def test_openai_compat_requires_key():
    client = OpenAICompatClient("https://x/v1", "", "m", "groq", "GROQ_API_KEY")
    with pytest.raises(LLMError):
        client.complete("hi")


def test_hash_embedding_is_deterministic_and_normalized(monkeypatch):
    from magpie.relevance import embeddings as em

    monkeypatch.setattr(em.settings, "embedding_provider", "hash")
    v1 = em.embed(["hello world"])
    v2 = em.embed(["hello world"])
    assert v1 == v2  # deterministic — safe to cache
    norm = math.sqrt(sum(x * x for x in v1[0]))
    assert abs(norm - 1.0) < 1e-6  # L2-normalized for cosine-as-dot-product
    assert em.embed(["completely unrelated text"])[0] != v1[0]


def test_unknown_embedding_provider_raises(monkeypatch):
    from magpie.relevance import embeddings as em

    monkeypatch.setattr(em.settings, "embedding_provider", "nope")
    with pytest.raises(LLMError):
        em.embed(["x"])
