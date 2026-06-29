"""Smoke tests — verify package imports and config load."""

from magpie import __version__
from magpie.config import settings


def test_version():
    assert __version__ == "0.1.0"


def test_settings_defaults():
    assert "duckduckgo" in settings.source_list
    assert settings.ollama_model
