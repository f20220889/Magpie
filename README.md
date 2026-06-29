# Magpie — Personal Technology Learning Agent

Magpie is a local, agentic learning assistant that discovers technologies relevant to a user's existing skills, summarizes them, and adapts as the user marks topics as learned. It runs entirely on free, open-source components hosted on the user's own machine and requires no paid APIs, subscriptions, or cloud services.

---

## 1. Problem Statement

Technology changes faster than any individual can track. New frameworks, tools, standards, and techniques appear continually, but most are not relevant to a given person's skills and goals. Generic news feeds, newsletters, and search engines surface broadly popular content rather than content matched to a specific individual's knowledge and learning trajectory. The result is a combination of missed developments and time wasted on material that is too basic, too advanced, or irrelevant.

Magpie addresses this by acting as a personal research assistant that:

1. Maintains a structured model of the user's current knowledge (domains, skills, and previously learned topics).
2. Accepts a free-form prompt describing what the user wants to explore.
3. Searches the web for new technologies and developments tied to that prompt and the user's knowledge profile.
4. Returns concise overviews with curated links, ranked by relevance to the user.
5. Lets the user commit a topic to their knowledge base as "learned," which feeds back into future runs so results become more personalized and less redundant.

Over time the system learns what the user already knows, avoids repeating it, and steers discovery toward adjacent, higher-value topics.

---

## 2. Goals and Non-Goals

### Goals
- Deliver personalized technology discovery rather than generic trending feeds.
- Produce sourced summaries with links; avoid unsourced claims.
- Continuously adapt to the user's evolving knowledge.
- Keep results concise and actionable — overview first, depth on demand.
- Run locally and privately; the knowledge base is the user's data.

### Non-Goals
- Not a general-purpose chatbot or coding assistant.
- Not a real-time news ticker; it runs on demand or on a schedule.
- Not a content aggregator that stores full articles — it stores summaries, metadata, and links.
- No multi-user or social features.

---

## 3. Core Concepts

| Concept | Description |
|--------|-------------|
| Knowledge Base (KB) | Structured store of the user's domains, skills, proficiency levels, and learned topics. The memory that personalizes results. |
| Domain Profile | The user's primary fields (e.g. Backend, DevOps, ML, Security) with weighted interest. |
| Prompt | A natural-language request, e.g. "What's new in serverless cold-start optimization?" |
| Discovery Run | One end-to-end cycle: prompt → search/scrape → summarize → rank → present. |
| Topic Card | The output unit: title, overview, why-it's-relevant, links, tags, relevance score. |
| Learning Event | Marking a Topic Card as learned, which enters the KB and reshapes future runs. |
| Relevance Engine | Scores candidate content against the KB and prompt to filter noise. |

---

## 4. Features

### Core
- Onboarding to capture initial domains, skills, and known topics.
- Prompt-driven discovery runs.
- Web search and scraping pipeline with content extraction.
- LLM-powered summarization into Topic Cards.
- Relevance ranking against the KB.
- "Add to knowledge" action that persists a Learning Event.
- Local persistence of the KB.
- Web UI (FastAPI plus a no-build single-page app) with live progress streaming.
- Run history (deduplicated) with restore, forget, and delete actions.

### Adaptive
- Deduplication against already-learned topics.
- Adjacency suggestions that propose the next logical topics given recent learning.
- Scheduled background runs (daily or weekly digests).
- Source-quality scoring and trust weighting.
- Feedback signals (thumbs up/down, "too basic", "too advanced", "irrelevant") that tune ranking.

### Extended
- Knowledge-graph visualization of learned topics and their tags.
- Ordered learning roadmaps generated from the KB.
- Multi-source connectors (DuckDuckGo, Hacker News, arXiv, GitHub, RSS), all free and keyless.
- Export to Markdown (Obsidian), Anki, and JSON.

---

## 5. Agentic Learning Loop

Each cycle informs the next.

```
            ┌─────────────────────────────────────────────┐
            │              KNOWLEDGE BASE                   │
            │  domains • skills • learned topics • signals  │
            └───────────────▲───────────────────┬──────────┘
                            │                    │
              (5) commit    │                    │  (1) context
              learned topic │                    ▼
            ┌───────────────┴──────┐   ┌──────────────────────┐
            │   USER REVIEW &       │   │   PROMPT + PROFILE    │
            │   "Add to knowledge"  │   │   → Query Planner     │
            └───────────────▲───────┘   └──────────┬───────────┘
                            │                       │ (2) search plan
                  (4) Topic │                       ▼
                     Cards  │           ┌──────────────────────┐
            ┌───────────────┴───────┐   │  SCRAPE + EXTRACT     │
            │  SUMMARIZE + RANK     │◄──┤  (web search, fetch)  │
            │  (Relevance Engine)   │   └──────────────────────┘
            └───────────────────────┘     (3) raw candidates
```

1. Context — load domains, skills, and learned topics from the KB.
2. Plan — expand the prompt into targeted search queries, biased by the profile and away from already-known topics.
3. Scrape and extract — search the web, fetch pages, extract clean content and metadata.
4. Summarize and rank — the LLM condenses each candidate into a Topic Card; the Relevance Engine scores against the KB and prompt; the top results are presented.
5. Commit — the user marks cards as learned, updating the KB, deduplication index, and interest weights, closing the loop.

---

## 6. Architecture

```
┌──────────────┐     ┌───────────────┐     ┌──────────────────┐
│   Frontend   │────▶│   API / Core  │────▶│   Agent Engine   │
│ (CLI or Web) │     │   (FastAPI)   │     │  (orchestrator)  │
└──────────────┘     └───────┬───────┘     └─────────┬────────┘
                             │                        │
                ┌────────────┼────────────┬───────────┼──────────────┐
                ▼            ▼            ▼            ▼              ▼
          ┌─────────┐  ┌──────────┐ ┌──────────┐ ┌─────────┐  ┌──────────┐
          │   KB    │  │  Search  │ │ Scraper/ │ │   LLM   │  │ Relevance│
          │ Store   │  │ Provider │ │ Extractor│ │ Provider│  │  Engine  │
          │(SQLite) │  │(multi-   │ │          │ │(Ollama, │  │(local    │
          │         │  │ source)  │ │          │ │ local)  │  │ embed)   │
          └─────────┘  └──────────┘ └──────────┘ └─────────┘  └──────────┘
```

### Component Responsibilities
- Frontend — captures prompts, renders Topic Cards, and exposes the learning actions. Available as a Typer CLI and a web UI.
- API / Core — request handling and persistence wiring (FastAPI).
- Agent Engine — orchestrates the loop: query planning, search, summarization, and ranking.
- KB Store — relational data (topics, skills, runs, signals) plus embeddings for semantic deduplication and relevance.
- Search Provider — a multi-source fan-out over free, keyless backends (DuckDuckGo, Hacker News, arXiv, GitHub, RSS, SearXNG), merged and deduplicated by URL. A failing source is skipped and does not interrupt a run.
- Scraper / Extractor — fetches and cleans HTML into readable text (httpx and trafilatura), with an on-disk cache for repeated URLs.
- LLM Provider — summarization, query expansion, and relevance reasoning via Ollama running a local open model such as `llama3.1` or `qwen2.5`.
- Relevance Engine — local embeddings and reranking to score candidates against the KB and prompt. It also applies feedback-learned adjustments: per-host and per-tag preference scores, aggregated from feedback signals and bounded with `tanh`, slightly raise sources and tags the user responds well to and lower the rest.

---

## 7. Technology Stack

All components are free and run locally. No paid API keys are required.

| Layer | Choice | Notes |
|-------|--------|-------|
| Language | Python 3.11+ | Ecosystem for scraping, ML, and LLM tooling. |
| Agent / LLM | Ollama with an open model (`llama3.1`, `qwen2.5`, `phi4`) | Runs locally; no API costs; private. |
| Web framework | FastAPI | Async, typed; serves the API and UI. |
| Search | Multi-source: DuckDuckGo (`ddgs`), Hacker News, arXiv, GitHub, RSS, or SearXNG | Free, keyless; results merged and deduplicated. |
| Scraping | httpx + trafilatura | Content extraction with a local cache. |
| Storage | SQLite | Local-first, zero-ops, private. |
| Embeddings | sentence-transformers (`bge-small-en`, `all-MiniLM-L6-v2`) | Semantic deduplication and relevance; runs offline. |
| Frontend | Typer/Rich CLI plus a no-build single-page app served by FastAPI | No build toolchain required. |
| Scheduler | cron / launchd | Background digest runs. |
| Config | pydantic-settings + `.env` | Typed configuration. |

The LLM provider is configurable. Ollama is the default; a hosted model can be substituted by changing configuration if stronger summaries are desired.

---

## 8. Data Model

```sql
-- Domains the user works in
domain(id, name, weight, created_at)

-- Specific skills under a domain
skill(id, domain_id, name, proficiency, created_at)

-- Topics the user has learned
learned_topic(id, title, summary, source_url, tags, domain_id,
              learned_at, embedding)

-- A discovery run
run(id, prompt, created_at, status)

-- Candidate results produced by a run
topic_card(id, run_id, title, overview, why_relevant, links,
           tags, source_url, recency, relevance_score, status)
-- status: surfaced | dismissed | learned

-- Feedback signals for tuning relevance
signal(id, topic_card_id, type, value, created_at)
-- type: thumbs_up | thumbs_down | too_basic | too_advanced | irrelevant | learned
```

---

## 9. Usage

```bash
# One-time onboarding
$ magpie init
> Primary domains? Backend, DevOps
> Key skills? Python, Kubernetes, PostgreSQL
> Topics you already know well? (optional) REST APIs, Docker

# Run a discovery
$ magpie discover "what's new in reducing Kubernetes cold starts"

┌─ Topic 1 ──────────────────────────────────────────────┐
│ KEDA + Knative scale-to-zero improvements (2026)        │
│ Why relevant: builds on your Kubernetes skill; you      │
│ already know Docker but not event-driven autoscaling.   │
│ Overview: ...                                           │
│ Read more:                                              │
│   • https://...                                         │
│   • https://...                                         │
│ Recency: 3 days ago  ·  Relevance: 0.91                 │
└─────────────────────────────────────────────────────────┘

? Add to your knowledge base?  [learn/skip/quit]
> learn
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `magpie init` | Onboard: capture domains, skills, and known topics. |
| `magpie discover "<prompt>"` | Run the discovery loop (search, summarize, rank, learn). `--top N` to cap results. |
| `magpie suggest` | Suggest the next logical topics to learn, based on the KB. |
| `magpie roadmap` | Generate an ordered learning path from the KB. |
| `magpie export --fmt md\|json\|anki [--out FILE]` | Export learned topics. |
| `magpie digest` | Run discoveries seeded from suggestions; intended for scheduling. |
| `magpie serve` | Launch the local web UI (default http://127.0.0.1:8077; set `MAGPIE_PORT` or `--port` to change). |
| `magpie profile` | Show domains, skills, and learned topics. |
| `magpie learned` | List learned topics. |
| `magpie forget "<title>"` | Remove a learned topic from the KB. |
| `magpie doctor` | Verify the local Ollama LLM is reachable and the model is available. |

### Web UI

`magpie serve` opens a local single-page application with the following views:

- Discover — enter a prompt; progress streams live (plan, search, read, rank) over Server-Sent Events, and results render as Topic Cards. Suggestion chips seed the search with one click, and each card has feedback controls (thumbs up/down, too basic, too advanced, irrelevant) that tune future ranking.
- History — past runs, deduplicated by prompt; select one to restore its saved cards, or delete it.
- Hoard — learned topics, with a toggle for a knowledge graph (topics and tags, rendered as a dependency-free SVG force layout) and export to Markdown, JSON, or Anki.
- Path — an ordered learning roadmap generated from the KB; selecting a step runs a discovery for it.
- Profile — view and edit domains and skills.
- Status — Ollama health.

The UI supports a persisted dark mode, keyboard shortcuts (`/` to search, `1`–`6` to switch tabs, `t` to toggle theme), handwriting display accents (Caveat), and swappable logo and cursor assets in `ui/assets/`.

### HTTP API

Served by `magpie serve`:

| Method and path | Purpose |
|---------------|---------|
| `GET /api/health` | Ollama reachability and resolved model. |
| `GET /api/profile` · `POST /api/init` | Read or seed the profile. |
| `GET /api/suggestions` | Adjacency suggestions. |
| `GET /api/roadmap` | Ordered learning roadmap. |
| `GET /api/export?format=md\|json\|anki` | Download learned topics. |
| `GET /api/discover/stream?prompt=…` | Streaming discovery run (progress and cards). |
| `POST /api/discover` | Non-streaming discovery. |
| `POST /api/learn` | Commit a card as learned. |
| `POST /api/signal` | Record feedback to tune ranking. |
| `GET /api/learned` · `DELETE /api/learned/{id}` | List or remove learned topics. |
| `GET /api/history` · `GET /api/run/{id}` · `DELETE /api/run/{id}` | Run history, restore, and delete. |

### Scheduling a Digest

`magpie digest` selects suggested topics, runs discoveries, and saves the top cards for later review in the History view. It can be scheduled with the operating system's scheduler.

cron (Linux):
```cron
# every weekday at 8am — adjust the path to the venv and project
0 8 * * 1-5  cd /path/to/magpie && .venv/bin/magpie digest >> data/digest.log 2>&1
```

launchd (macOS): create `~/Library/LaunchAgents/com.magpie.digest.plist` with a `StartCalendarInterval` that runs `.venv/bin/magpie digest`, then load it with `launchctl load ~/Library/LaunchAgents/com.magpie.digest.plist`.

Ollama must be running for the digest to summarize. The job is idempotent and stores only new, non-duplicate cards.

---

## 10. Implementation Phases

1. Foundations — project scaffold, configuration, KB schema, onboarding.
2. Core loop — prompt, search, scrape, summarize, cards, learn.
3. Adaptation — deduplication, adjacency suggestions, feedback signals, scheduling.
4. Extended — knowledge graph, learning roadmaps, multi-source connectors, exports.

---

## 11. Design Considerations

- Choice of search backend (DuckDuckGo rate limits versus a self-hosted SearXNG instance).
- Selection of an Ollama model that balances quality and speed for the available hardware.
- Deduplication aggressiveness, balancing novelty against useful refreshers.
- Measuring relevance success through explicit feedback versus implicit signals.
- Remaining single-user and local versus a future hosted, multi-user deployment.

---

## 12. Getting Started

```bash
# 1. Install Ollama (local LLM runtime) and pull a model
#    https://ollama.com/download
ollama pull llama3.1        # or qwen2.5 / phi4

# 2. Set up the project
git clone <repo-url>
cd magpie
python -m venv .venv && source .venv/bin/activate
pip install -e .            # installs dependencies and the `magpie` command
cp .env.example .env        # model and search settings; no API keys required

# 3. Onboard and run
magpie init
magpie discover "what's new in <your topic>"

# Or use the web UI
magpie serve     # http://127.0.0.1:8077

# Or run the end-to-end demo (isolated demo database)
.venv/bin/python scripts/demo.py
```

Scraped pages are cached under `data/cache/` (`CACHE_TTL_HOURS`, default one week) so repeated URLs across prompts and sources skip the network. Set `CACHE_TTL_HOURS=0` to disable caching.

Configuration lives in `.env`; relevant keys include `OLLAMA_MODEL` and `SEARCH_SOURCES`.

### Project Layout

```
magpie/            # Python package
  cli.py           # Typer CLI
  config.py        # typed .env settings
  agent/           # orchestrator, query planner, adjacency, roadmap, digest
  knowledge/       # SQLite KB: models and store (including feedback signals)
  search/          # multi-source: duckduckgo, hackernews, arxiv, github, rss, searxng
  scraper/         # fetch and extract (trafilatura) with cache
  llm/             # local Ollama client
  relevance/       # local embeddings, ranking/dedup, feedback nudges
  summarize/       # content to Topic Card
  exporter.py      # learned topics to Markdown / JSON / Anki
  web/             # FastAPI app and JSON/SSE API
ui/                # no-build SPA (index.html, css/, js/, assets/)
scripts/demo.py    # end-to-end demo against the real pipeline
tests/             # pytest suite
data/              # KB and scrape cache (gitignored)
```

### Development

```bash
pip install -e ".[dev]"     # adds pytest and ruff
pytest -q                   # full test suite (mocked; no Ollama or network required)
ruff check magpie tests     # lint
```

The test suite mocks the LLM, network, and embedding model, so it runs quickly with only light dependencies. GitHub Actions (`.github/workflows/ci.yml`) runs lint and tests on Python 3.11 and 3.12 for every push and pull request.

---

## 13. License

To be determined (MIT suggested).
