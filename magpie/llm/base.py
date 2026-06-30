"""Common LLM interface shared by the local (Ollama) and hosted providers.

Every client exposes ``complete``/``complete_json``/``health`` so the rest of the
app is provider-agnostic — swap providers via ``LLM_PROVIDER`` with no code
changes. ``LLMError`` is the single error type callers catch.
"""

from __future__ import annotations

from typing import Protocol


class LLMError(RuntimeError):
    """Raised when an LLM provider is unreachable, misconfigured, or misbehaves."""


class LLMClient(Protocol):
    def complete(
        self, prompt: str, system: str | None = None, json_mode: bool = False
    ) -> str: ...

    def complete_json(self, prompt: str, system: str | None = None) -> dict | list: ...

    def complete_vision_json(
        self, prompt: str, image_b64: str, mime: str, system: str | None = None
    ) -> dict | list:
        """Read an image (base64) plus prompt and return parsed JSON.

        Requires a vision-capable model; raises ``LLMError`` if unavailable.
        """
        ...

    def health(self) -> dict: ...
