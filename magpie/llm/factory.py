"""Build the configured LLM client. One switch (``LLM_PROVIDER``) for the app.

All hosted options are free-tier and OpenAI-compatible, so they share one
client. ``ollama`` stays the local default for development.
"""

from __future__ import annotations

import os
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


def _is_hosted_env() -> bool:
    """True on a hosting platform, where there is no local Ollama to reach.

    Render sets ``RENDER`` on every service; ``MAGPIE_HOSTED`` is a generic
    escape hatch for other hosts.
    """
    return bool(os.getenv("RENDER") or os.getenv("MAGPIE_HOSTED"))


def _autodetect_hosted_provider() -> str | None:
    """Pick a hosted provider whose API key is set (first match wins)."""
    for name, preset in PROVIDERS.items():
        if getattr(settings, preset.key_setting, ""):
            return name
    return None


def get_llm() -> LLMClient:
    """Return the LLM client for the configured provider.

    Ollama is the local-dev default. On a hosting platform there is no local
    Ollama, so rather than failing against ``localhost`` we auto-select a hosted
    provider when its API key is set (a deploy then only needs the key, not also
    LLM_PROVIDER) — or raise an actionable error pointing at the real fix.
    """
    name = (settings.llm_provider or "ollama").strip().lower()
    if name in ("ollama", "local", ""):
        if _is_hosted_env():
            auto = _autodetect_hosted_provider()
            if auto is None:
                raise LLMError(
                    "No LLM is configured for this deploy. Ollama only works "
                    "locally; on a host set a free provider, e.g. "
                    "LLM_PROVIDER=groq and GROQ_API_KEY=<key>, in the "
                    "environment, then redeploy."
                )
            name = auto
        else:
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
