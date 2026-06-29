"""Build the configured LLM client. One switch (``LLM_PROVIDER``) for the app.

All hosted options are free-tier and OpenAI-compatible, so they share one
client. ``ollama`` stays the local default for development.
"""

from __future__ import annotations

from dataclasses import dataclass

from magpie.config import settings
from magpie.llm.base import LLMClient, LLMError


@dataclass(frozen=True)
class _Preset:
    base_url: str
    default_model: str
    key_setting: str  # attribute on settings holding the API key


# Free-tier providers. default_model picks a capable free model; override with
# LLM_MODEL. base_url is each provider's OpenAI-compatible endpoint.
PROVIDERS: dict[str, _Preset] = {
    "groq": _Preset(
        "https://api.groq.com/openai/v1", "llama-3.3-70b-versatile", "groq_api_key"
    ),
    "gemini": _Preset(
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "gemini-2.0-flash",
        "gemini_api_key",
    ),
    "openrouter": _Preset(
        "https://openrouter.ai/api/v1",
        "meta-llama/llama-3.3-70b-instruct:free",
        "openrouter_api_key",
    ),
    "cerebras": _Preset(
        "https://api.cerebras.ai/v1", "llama-3.3-70b", "cerebras_api_key"
    ),
    "mistral": _Preset(
        "https://api.mistral.ai/v1", "mistral-small-latest", "mistral_api_key"
    ),
    "together": _Preset(
        "https://api.together.xyz/v1",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "together_api_key",
    ),
}


def get_llm() -> LLMClient:
    """Return the LLM client for the configured provider."""
    name = (settings.llm_provider or "ollama").strip().lower()
    if name in ("ollama", "local", ""):
        from magpie.llm.ollama_client import OllamaClient

        return OllamaClient()
    preset = PROVIDERS.get(name)
    if preset is None:
        raise LLMError(
            f"unknown LLM_PROVIDER '{name}'. "
            f"options: ollama, {', '.join(PROVIDERS)}"
        )
    from magpie.llm.openai_compat import OpenAICompatClient

    return OpenAICompatClient(
        base_url=preset.base_url,
        api_key=getattr(settings, preset.key_setting, ""),
        model=settings.llm_model or preset.default_model,
        provider=name,
        key_hint=preset.key_setting.upper(),
    )
