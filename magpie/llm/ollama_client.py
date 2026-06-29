"""Thin wrapper over a local Ollama model.

All free / local. Provides a health check and a clear error when the
server is down or the configured model isn't pulled, so failures are
actionable instead of cryptic.
"""

from __future__ import annotations

from magpie.config import settings
from magpie.llm.base import LLMError


class OllamaError(LLMError):
    """Raised when Ollama is unreachable or the model is unavailable."""


class OllamaClient:
    def __init__(self, model: str | None = None, host: str | None = None) -> None:
        self.model = model or settings.ollama_model
        self.host = host or settings.ollama_host

    def _client(self):
        import ollama

        return ollama.Client(host=self.host)

    def available_models(self) -> list[str]:
        """Return the list of pulled model names, or raise OllamaError."""
        try:
            resp = self._client().list()
        except Exception as e:  # connection refused, etc.
            raise OllamaError(
                f"Cannot reach Ollama at {self.host}. Is it running? "
                "Start it with `ollama serve`."
            ) from e
        return [m.get("model") or m.get("name") for m in resp.get("models", [])]

    def _resolve_model(self, available: list[str]) -> str:
        """Match the configured model against pulled tags.

        Accepts an exact match, or a bare name that matches a single
        ``name:tag`` (e.g. ``llama3.1`` -> ``llama3.1:8b``).
        """
        if self.model in available:
            return self.model
        matches = [m for m in available if m.split(":")[0] == self.model.split(":")[0]]
        if len(matches) == 1:
            return matches[0]
        if matches:
            return matches[0]
        raise OllamaError(
            f"Model '{self.model}' is not pulled. Available: {available or 'none'}. "
            f"Pull it with `ollama pull {self.model}`."
        )

    def health(self) -> dict:
        """Return a status dict describing reachability and model resolution."""
        available = self.available_models()
        resolved = self._resolve_model(available)
        return {"host": self.host, "available": available, "resolved_model": resolved}

    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> str:
        """Single-shot chat completion against the resolved local model.

        When ``json_mode`` is set, Ollama is constrained to emit valid JSON.
        """
        available = self.available_models()
        model = self._resolve_model(available)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        kwargs = {"format": "json"} if json_mode else {}
        try:
            resp = self._client().chat(model=model, messages=messages, **kwargs)
        except Exception as e:
            raise OllamaError(f"Ollama chat failed for model '{model}': {e}") from e
        return resp["message"]["content"]

    def complete_json(self, prompt: str, system: str | None = None) -> dict | list:
        """Complete in JSON mode and parse the result. Raises OllamaError on bad JSON."""
        import json

        raw = self.complete(prompt, system=system, json_mode=True)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise OllamaError(f"Model did not return valid JSON: {raw[:200]}") from e
