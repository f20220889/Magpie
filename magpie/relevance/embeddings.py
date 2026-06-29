"""Text embeddings with a provider switch (``EMBEDDING_PROVIDER``).

  local  — sentence-transformers, best quality, needs torch (default, offline).
  gemini — free hosted API (needs GEMINI_API_KEY); no heavy local deps.
  hash   — keyless, dependency-free fallback so any free host can run with no
           model and no key. Lower quality, but the pipeline never breaks.

All providers return L2-normalized vectors, so the relevance engine can treat
cosine similarity as a plain dot product.
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache

import httpx

from magpie.config import settings
from magpie.llm.base import LLMError

_HASH_DIM = 256


@lru_cache(maxsize=1)
def _local_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(settings.embedding_model)


def _local_embed(texts: list[str]) -> list[list[float]]:
    return _local_model().encode(texts, normalize_embeddings=True).tolist()


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _hash_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic bag-of-words hashing embedding — keyless and dependency-free."""
    out: list[list[float]] = []
    for text in texts:
        vec = [0.0] * _HASH_DIM
        for token in text.lower().split():
            digest = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            vec[digest % _HASH_DIM] += 1.0
            sign = 1.0 if (digest >> 8) & 1 else -1.0  # signed to spread mass
            vec[(digest // _HASH_DIM) % _HASH_DIM] += sign
        out.append(_normalize(vec))
    return out


def _gemini_embed(texts: list[str]) -> list[list[float]]:
    key = settings.gemini_api_key
    if not key:
        raise LLMError("EMBEDDING_PROVIDER=gemini needs GEMINI_API_KEY")
    model = settings.gemini_embedding_model
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:embedContent?key={key}"
    )
    out: list[list[float]] = []
    for text in texts:
        try:
            resp = httpx.post(
                url,
                json={"model": f"models/{model}", "content": {"parts": [{"text": text}]}},
                timeout=settings.llm_timeout,
            )
            resp.raise_for_status()
            values = resp.json()["embedding"]["values"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise LLMError(f"Gemini embedding failed: {e}") from e
        out.append(_normalize(values))
    return out


_PROVIDERS = {
    "local": _local_embed,
    "gemini": _gemini_embed,
    "hash": _hash_embed,
}


def embed(texts: list[str]) -> list[list[float]]:
    provider = (settings.embedding_provider or "local").strip().lower()
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise LLMError(
            f"unknown EMBEDDING_PROVIDER '{provider}'. options: {', '.join(_PROVIDERS)}"
        )
    return fn(texts)
