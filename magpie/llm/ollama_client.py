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

    def _resolve_model(self, available: list[str], model: str | None = None) -> str:
        """Match a model name against pulled tags (defaults to the chat model).

        Accepts an exact match, or a bare name that matches a single
        ``name:tag`` (e.g. ``llama3.1`` -> ``llama3.1:8b``).
        """
        want = model or self.model
        if want in available:
            return want
        matches = [m for m in available if m.split(":")[0] == want.split(":")[0]]
        if matches:
            return matches[0]
        raise OllamaError(
            f"Model '{want}' is not pulled. Available: {available or 'none'}. "
            f"Pull it with `ollama pull {want}`."
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

    def complete_vision_json(
        self, prompt: str, image_b64: str, mime: str, system: str | None = None
    ) -> dict | list:
        """Read an image with a local vision model (e.g. llama3.2-vision) -> JSON.

        Uses ``LLM_VISION_MODEL`` if set, else defaults to ``llama3.2-vision``;
        the model must be pulled or we raise an actionable OllamaError.
        """
        import json

        want = settings.llm_vision_model or "llama3.2-vision"
        available = self.available_models()
        model = self._resolve_model(available, want)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt, "images": [image_b64]})
        try:
            resp = self._client().chat(model=model, messages=messages, format="json")
        except Exception as e:
            raise OllamaError(f"Ollama vision chat failed for model '{model}': {e}") from e
        raw = resp["message"]["content"]
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise OllamaError(f"Model did not return valid JSON: {raw[:200]}") from e
