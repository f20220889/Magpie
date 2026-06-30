"""Typed configuration loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- LLM provider selection ---
    # "ollama" (local) for dev; any hosted free provider for global deploy:
    #   groq | gemini | openrouter | cerebras | mistral | together
    llm_provider: str = "ollama"
    llm_model: str = ""        # blank => the provider's free default
    # Vision-capable model for reading image resumes (OCR via the LLM). Blank =>
    # the hosted client reuses llm_model; Ollama falls back to "llama3.2-vision".
    llm_vision_model: str = ""
    llm_timeout: int = 60

    # LLM (Ollama, local)
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # Hosted-provider API keys (each has a free tier; only the selected one is used)
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    cerebras_api_key: str = ""
    mistral_api_key: str = ""
    together_api_key: str = ""

    # Search — comma list of sources, all free/keyless:
    # duckduckgo | hackernews | arxiv | github | rss | searxng
    search_sources: str = "duckduckgo,hackernews,arxiv,github"
    searxng_url: str = "http://localhost:8080"
    rss_feeds: str = ""  # comma-separated feed URLs (only used if 'rss' enabled)

    @property
    def source_list(self) -> list[str]:
        return [s.strip() for s in self.search_sources.split(",") if s.strip()]

    # Embeddings
    # "local" (sentence-transformers; best quality, needs torch) |
    # "gemini" (free hosted, needs gemini_api_key) |
    # "hash" (keyless, dependency-free fallback so any free host can run)
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    gemini_embedding_model: str = "text-embedding-004"

    # Storage
    # Local dev defaults to a SQLite file. For global deploy set DATABASE_URL to a
    # Postgres DSN (e.g. postgresql+psycopg://user:pass@host:5432/magpie) so data
    # survives restarts on hosts with ephemeral disks. SQLite is used when blank.
    db_path: str = "data/magpie.db"
    database_url: str = ""

    # Discovery tuning
    max_results: int = 8
    scrape_timeout: int = 15

    # Relevance. Candidates are shortlisted by snippet relevance BEFORE the slow
    # scrape, so fetches are spent on the most promising URLs (not the first N).
    # candidate_pool bounds how many search hits are scored before shortlisting
    # (keeps embedding cost predictable). Final cards scoring below min_relevance
    # (cosine vs the query) are dropped as off-topic.
    candidate_pool: int = 40
    min_relevance: float = 0.12

    # Resume import: max upload size accepted by /api/skills/extract.
    max_upload_mb: int = 8

    # Scraper HTTP — a realistic User-Agent avoids bot-walls that serve 403s or
    # empty shells to default clients (a top cause of inaccurate/missing cards).
    scrape_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    # Extractions shorter than this are treated as misses (bot-walls, nav-only
    # chrome) rather than real article content, so they never become cards.
    min_content_chars: int = 250

    # Scrape cache (avoid re-fetching the same URL)
    cache_dir: str = "data/cache"
    cache_ttl_hours: int = 168  # 1 week; set 0 to disable caching

    # Auth / sessions
    session_cookie: str = "magpie_session"
    session_days: int = 14
    cookie_secure: bool = False  # set True behind HTTPS in production

    # Google OAuth (optional — sign-in button shows only when client_id is set)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""  # e.g. http://localhost:8077/api/auth/google/callback

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


settings = Settings()
