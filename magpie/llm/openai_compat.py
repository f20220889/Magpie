"""One client for every OpenAI-compatible hosted provider.

Groq, Google Gemini (OpenAI-compat endpoint), OpenRouter, Cerebras, Mistral and
Together all speak the OpenAI chat-completions API, so a single client covers
them — only the base URL, model, and API key differ (see ``factory.py``). All
have a free tier, keeping the project's no-paid-API constraint for deploy.
"""

from __future__ import annotations

import json

import httpx

from magpie.config import settings
from magpie.llm.base import LLMError


def _strip_fences(text: str) -> str:
    """Some models wrap JSON in ```json fences despite instructions — peel them."""
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


class OpenAICompatClient:
    def __init__(
        self, base_url: str, api_key: str, model: str, provider: str, key_hint: str
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.key_hint = key_hint  # env var name, for actionable error messages

    def _require_key(self) -> None:
        if not self.api_key:
            raise LLMError(
                f"{self.provider}: no API key. Set {self.key_hint} in your environment."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> str:
        self._require_key()
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict = {"model": self.model, "messages": messages, "temperature": 0.2}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=body,
                timeout=settings.llm_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300]
            raise LLMError(f"{self.provider} HTTP {e.response.status_code}: {detail}") from e
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMError(f"{self.provider} request failed: {e}") from e

    def complete_json(self, prompt: str, system: str | None = None) -> dict | list:
        raw = self.complete(prompt, system=system, json_mode=True)
        try:
            return json.loads(_strip_fences(raw))
        except json.JSONDecodeError as e:
            raise LLMError(f"{self.provider} did not return valid JSON: {raw[:200]}") from e

    def health(self) -> dict:
        self._require_key()
        available: list[str] = []
        try:
            resp = httpx.get(
                f"{self.base_url}/models", headers=self._headers(), timeout=15
            )
            resp.raise_for_status()
            available = [m.get("id") for m in resp.json().get("data", []) if m.get("id")]
        except httpx.HTTPStatusError as e:
            raise LLMError(
                f"{self.provider} rejected the key ({e.response.status_code}). "
                f"Check {self.key_hint}."
            ) from e
        except (httpx.HTTPError, ValueError):
            available = []  # provider may not expose /models — not fatal
        return {
            "host": self.base_url,
            "available": available[:50] or [self.model],
            "resolved_model": self.model,
        }
