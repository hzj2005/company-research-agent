# Company Research Agent

> **二次开发声明 / Attribution**
> 本仓库**基于** [guy-hartstein/company-research-agent](https://github.com/guy-hartstein/company-research-agent)（Apache-2.0）**二次开发**，落地 commit `23fe92d`。原版的四路并行检索、Tavily 相关性筛选、PDF 导出、SSE 进度与多语言 README **均不是本项目的独立设计**；`LICENSE` 与上游 commit 历史完整保留。详见 [`docs/UPSTREAM.md`](docs/UPSTREAM.md)。
>
> **What this fork adds**: a LangGraph state workflow with evidence-sufficiency checks, a bounded self-correction loop, per-section abstention instead of fabrication, reducer-based parallel writes and real SQLite checkpointing (`graph/`, `capabilities/`, `persistence/`, `config/`, `tests/`). Design and measured baseline: [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md), [`docs/BASELINE.md`](docs/BASELINE.md).
>
> **Current status — read before running**: the new graph runs in `fixture` mode on synthetic data and needs no API key (`uv run python -m graph.run --case sparse --show-report`). The FastAPI `/research` endpoint and the LangGraph Studio entry **still point to the upstream linear DAG**; they will be switched to the new graph when real LLM/retrieval is wired (S5). No accuracy, latency or cost figures are claimed until live evaluation (S8) actually runs.

An agentic research tool that turns a company name into a structured, source-backed briefing. The FastAPI backend coordinates specialized research and synthesis steps; the React interface tracks the job and lets you export the finished report as a PDF.

![Company Research Agent landing page](static/app-screenshot.png)

## What it does

- Researches a company’s business, industry, financial context, and recent news.
- Uses Tavily search and relevance scoring to find and curate source material.
- Runs on any model available through [OpenRouter](https://openrouter.ai) — pick it from the in-app Settings — or on direct OpenAI/Gemini keys.
- Streams research progress to the browser and supports PDF export.
- Optionally persists jobs and reports in MongoDB.
- **This fork also adds** a separate LangGraph workflow (`graph/`) with evidence-sufficiency checks, a bounded self-correction loop, per-section abstention instead of fabrication, and SQLite checkpointing. It runs today from the CLI in `fixture` mode with no API key.

## Architecture

Two graphs live in this repository. **The FastAPI `/research` endpoint and LangGraph Studio still use the upstream graph** (see "Current status" above); the reworked graph is exercised through the CLI until real LLM/retrieval is wired in S5.

### Upstream — unchanged

```text
React + Vite UI → POST /research → FastAPI application → Research graph
  analyzers → collector → curator → briefing → editor
  Tavily search + relevance scoring · OpenRouter / OpenAI / Gemini · PDF export · SSE progress
```

The UI connects to the API with `VITE_API_URL` and receives incremental updates from `GET /research/{job_id}/stream`.

### This fork — `graph/` (7-node main graph + parallel research subgraph)

```text
START → grounding → [research subgraph] → curate → evidence_check
                          ↑                    ├─ pass    → briefing → END
                          │                    ├─ retry   → rewrite_query ─┘
                          │                    └─ degrade → degrade ──────→ briefing → END

research subgraph:  START → dispatch ──Send──→ analyst(company)
                                    ──Send──→ analyst(industry)
                                    ──Send──→ analyst(financial)
                                    ──Send──→ analyst(news)    → END
                    retry rounds dispatch only sections in `sections_to_research`
```

- `Send` fans out four analysts in parallel; reducer-backed state merges their writes without overwrites (measured: 4 branches 0.181s vs 0.600s sequential).
- `evidence_check` is a real node with three conditional edges. Retry is bounded by `max_retry` (2) and ends in an explicit "no public evidence found" abstention, never invented facts.
- Every step is persisted by an `AsyncSqliteSaver` checkpointer (`persistence/checkpointer.py`) and survives a restart.
- The data source is currently an `@tool`-wrapped local fixture (`capabilities/retrieval.py`); real Tavily + structured LLM output is S5.

```bash
uv run python -m graph.run --case sparse --show-report --trace
```

## Prerequisites

The keys below are for the **upstream FastAPI/React app**. The reworked `graph/` CLI
needs none of them in `fixture` mode.

- Python 3.11 (`.python-version`; the reworked graph and its tests are pinned to 3.11)
- Node.js 18 or later
- An [OpenRouter API key](https://openrouter.ai/keys) — set in the backend `.env` or pasted into the app's Settings (alternatively, an OpenAI key, plus an optional Gemini key)
- A Tavily API key entered in the app for each research session (or a backend fallback key)
- A Google Maps API key only if you want location autocomplete
- MongoDB only if you want persistent jobs and reports

## Run locally

1. Create the environment from the lockfile (uv / Python 3.11 — see `.python-version`):

   ```bash
   uv sync --frozen
   uv run python -m pytest -q
   ```

   `pyproject.toml` + `uv.lock` are the source of truth for the reworked graph and its tests.
   The upstream `requirements.txt` is kept only for the original FastAPI/React app; do not
   `pip install -r requirements.txt` into this environment — it bypasses the lockfile and
   makes the result non-reproducible.

2. Create `.env` from the example and set the required backend keys:

   ```bash
   cp .env.example .env
   ```

   ```env
   # Recommended: one key for every model (or paste a key in the app's Settings instead)
   OPENROUTER_API_KEY=your_openrouter_key
   # Optional default model; users can still pick another in Settings
   # OPENROUTER_MODEL=anthropic/claude-sonnet-5.5
   # Alternative to OpenRouter: direct provider keys
   # OPENAI_API_KEY=your_openai_key
   # GEMINI_API_KEY=your_gemini_key
   # Optional fallback when no per-session Tavily key is supplied
   TAVILY_API_KEY=your_tavily_key
   # MONGODB_URI=optional_mongodb_connection_string
   ```

3. Configure the frontend:

   ```bash
   cp ui/.env.development.example ui/.env.development.local
   cd ui && npm install && cd ..
   ```

   Set `VITE_API_URL=http://localhost:8000` in `ui/.env.development.local`. Add `VITE_GOOGLE_MAPS_API_KEY` only when location autocomplete is needed.

4. Start the API in one terminal:

   ```bash
   .venv/bin/uvicorn application:app --reload --port 8000
   ```

5. Start the UI in a second terminal:

   ```bash
   cd ui
   npm run dev
   ```

Open [http://localhost:5174](http://localhost:5174). The API is available at [http://localhost:8000/docs](http://localhost:8000/docs).

Alternatively, `./setup.sh` installs everything, asks for your Tavily and OpenRouter keys, and writes `.env` for you.

### Choosing a model

Click the model button in the top-right corner to open **Settings**. There you can paste an OpenRouter key (stored only in your browser and sent with each research request) and search or filter the full OpenRouter catalog by provider. The selected model is used for every step of the research pipeline. If no OpenRouter key is available, the backend falls back to `OPENAI_API_KEY` (with Gemini for briefings when `GEMINI_API_KEY` is set).

## Docker

After creating the root `.env` and `ui/.env.development.local` files, run:

```bash
docker compose up --build
```

This exposes the API on port `8000` and the UI on port `5174`.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/research` | Start a research job. Accepts optional `openrouter_api_key` and `model`. |
| `GET` | `/models` | List text models available on OpenRouter (cached for an hour). |
| `GET` | `/config` | Report which LLM keys the server has configured and the default model. |
| `GET` | `/research/{job_id}/stream` | Receive server-sent progress and completion events. |
| `GET` | `/research/{job_id}/report` | Retrieve a completed report. |
| `POST` | `/generate-pdf` | Generate a PDF from report Markdown. |
| `GET` | `/research/pdf/{filename}` | Download a generated PDF. |

Example request:

```bash
curl -X POST http://localhost:8000/research \
  -H 'Content-Type: application/json' \
  -d '{
    "company": "Tavily",
    "company_url": "https://tavily.com",
    "industry": "AI search",
    "hq_location": "New York, USA",
    "model": "anthropic/claude-sonnet-5.5"
  }'
```

`model` and `openrouter_api_key` are optional. When `openrouter_api_key` is omitted, the backend uses `OPENROUTER_API_KEY` from its environment; when neither is set, it falls back to OpenAI/Gemini and ignores `model`.

## Configuration reference

| Variable | Required | Used by |
| --- | --- | --- |
| `TAVILY_API_KEY` | No | Backend fallback for research and curation; visitors can supply their own key in the UI |
| `OPENROUTER_API_KEY` | No* | All LLM steps via OpenRouter; users can supply their own key in Settings instead |
| `OPENROUTER_MODEL` | No | Default OpenRouter model (`google/gemini-3.8-flash` if unset) |
| `OPENAI_API_KEY` | No* | Research and editing when no OpenRouter key is available |
| `GEMINI_API_KEY` | No | Briefing synthesis when no OpenRouter key is available (falls back to OpenAI) |
| `MONGODB_URI` | No | Backend job/report persistence |
| `VITE_API_URL` | Yes | Frontend API connection |
| `VITE_GOOGLE_MAPS_API_KEY` | No | Frontend location autocomplete |

\* An LLM key is needed from somewhere: `OPENROUTER_API_KEY`, `OPENAI_API_KEY`, or an OpenRouter key entered in the app's Settings.

## License

[Apache License 2.0](LICENSE)
