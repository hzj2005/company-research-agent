# Company Research Agent

> **二次开发声明 / Attribution**
> 本仓库**基于** [guy-hartstein/company-research-agent](https://github.com/guy-hartstein/company-research-agent)（Apache-2.0）**二次开发**，落地 commit `23fe92d`。原版的四路并行检索、Tavily 相关性筛选、PDF 导出、SSE 进度与多语言 README **均不是本项目的独立设计**；`LICENSE` 与上游 commit 历史完整保留。详见 [`docs/UPSTREAM.md`](docs/UPSTREAM.md)。
>
> **What this fork adds**: a LangGraph state workflow with evidence-sufficiency checks, a bounded self-correction loop, per-section abstention instead of fabrication, reducer-based parallel writes and real SQLite checkpointing (`graph/`, `capabilities/`, `persistence/`, `config/`, `tests/`). Design and measured baseline: [`docs/PROJECT_PLAN.md`](docs/PROJECT_PLAN.md), [`docs/BASELINE.md`](docs/BASELINE.md).
>
> **Current status — read before running**: the new graph runs in `fixture` mode on synthetic data and needs no API key (`uv run python -m graph.run --case sparse --show-report`). Since S5-B both **FastAPI `/research` and the LangGraph Studio entry point to the new graph**; `/research` currently consumes only `company` (legacy fields such as `industry` or a request-body API key are ignored). `briefing` runs a real `with_structured_output` LCEL chain against a **local deterministic mock backend**, not a real model. **Zero live Tavily / model calls have been made** — real retrieval is behind a three-way opt-in (`APP_MODE=live` + `TAVILY_LIVE_ENABLED=true` + `TAVILY_MAX_CALLS>0`), a hard per-run call budget and a disk cache, to protect the free quota. S8.0 read-only audit and S8.1 zero-request dry-run are done; no accuracy, latency or cost figures are claimed until live evaluation (S8.2+) is explicitly approved and actually runs.

An agentic research tool that turns a company name into a structured, source-backed briefing. The FastAPI backend coordinates specialized research and synthesis steps; the React interface tracks the job and lets you export the finished report as a PDF.

![Company Research Agent landing page](static/app-screenshot.png)

## What it does

- Researches a company’s business, industry, financial context, and recent news.
- Uses Tavily search and relevance scoring to find and curate source material.
- Runs on any model available through [OpenRouter](https://openrouter.ai) — pick it from the in-app Settings — or on direct OpenAI/Gemini keys.
- Streams research progress to the browser and supports PDF export.
- Optionally persists jobs and reports in MongoDB.
- **This fork also adds** a LangGraph workflow (`graph/`) with evidence-sufficiency checks, a bounded self-correction loop, per-section abstention instead of fabrication, structured output with URL-level traceability, and SQLite checkpointing. It runs today from the CLI, `/research` and LangGraph Studio in `fixture` mode with no API key and zero external calls.

## Architecture

Two graphs live in this repository. Since S5-B, **both public entry points (`application.py` → `/research`, and `langgraph_entry.py` → Studio) compile the reworked `graph/`**; the upstream linear DAG is kept only as an untouched reference. All entry points currently run `fixture` mode; live retrieval is explicitly disabled by default.

### Upstream — unchanged (reference only, no longer wired to the entry points)

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
- `briefing` has two paths behind `features.structured_output`: **on** runs `prompt | model.with_structured_output(SectionBrief)` with URL-level traceability and bounded validation retry; **off** keeps the S4 template and produces a byte-identical report (A/B baseline). In `fixture` mode the "model" is a local `httpx.MockTransport` deterministic stub — **not a real model capability**.
- The data source is an `@tool`-wrapped fixture by default (`capabilities/retrieval.py`). `live` mode adds `TavilyRetriever(BaseRetriever)` plus a call budget, disk cache and dry-run; it is **disabled by default** even when a key is installed.
- **S6 HITL** is opt-in: with `FEATURES_HUMAN_REVIEW=true` and `AUTO_APPROVE_REVIEW=false`, an extra `human_review` node calls `interrupt()` before `briefing` and the run pauses. A second CLI process resumes it from the SQLite checkpoint with `Command(resume=...)`. A reviewer can approve, reject the whole report, or reject selected sections — rejected sections abstain instead of inventing content. Default `FEATURES_HUMAN_REVIEW=false` keeps the main graph at exactly 7 nodes.

```bash
uv run python -m graph.run --case sparse --show-report --trace
# A/B: FEATURES_STRUCTURED_OUTPUT=false uv run python -m graph.run --case sparse --trace
# live 检索需显式放行：APP_MODE=live TAVILY_LIVE_ENABLED=true TAVILY_MAX_CALLS=1
# 先看会发哪些 query（0 次真实请求）：TAVILY_DRY_RUN=true ...

# S6 人工复核（两步，两个独立进程，共用同一个 db）
uv run python -m graph.run --case sparse --review --db ./data/review.db
uv run python -m graph.run --resume --case sparse --db ./data/review.db \
  --decision reject-sections --reject-sections news --show-report
```

## Evaluation (S7)

One command runs the whole eval suite in `fixture` mode and writes `evals/scorecard.json`:

```bash
uv run python -m evals.run_eval                 # 6 A/B groups x 3 cases, 18 real graph runs
uv run python -m evals.build_golden --check    # CI: golden set in sync with fixture/settings
uv run python -m evals.run_eval --compare evals/scorecard.json --output evals/scorecard.next.json
```

`.github/workflows/eval.yml` runs `pytest` + the scorecard + a regression gate against the committed baseline; regressions beyond `0.02` fail the build and print the degraded golden item ids (e.g. `sparse:company:2`).

> **Read this before quoting any number.** The golden set is **derived from the synthetic fixture corpus** (`provenance: synthetic-fixture-derived`), not from real company facts. A baseline score of `1.000` means "the system reproduces the given documents with correct citations under the configured rules" — a **contract-regression test**, not model accuracy. `citation_traceability` here is a lexical-containment proxy, not semantic entailment; `cost_per_report` is `0.0` because there are zero external calls. The planned 30–50 human-verified companies require real retrieval + keys and belong to a later live-measurement stage. None of these numbers should be presented as real-world accuracy in a résumé.

`no_inline_citations` is a deliberately broken **negative control** (inline citations switched off): it scores `citation_traceability=0.0` / `hallucination_rate=1.0` on purpose, so a future change that removes citations shows up in the scorecard immediately. That `1.0` is not a measured hallucination rate of the default configuration.

The evaluator refuses to start unless `APP_MODE=fixture` and installs a non-loopback `socket.connect` guard while running, so it cannot consume Tavily or LLM quota even if configuration is changed by mistake. Measured: `tavily=0, llm=0, blocked_connection_attempts=0`.

## Live readiness / dry-run (S8.0–S8.1)

No live call has been made. `S8.0` is a read-only audit and `S8.1` is a **0-request dry-run** of the full graph:

```bash
uv run python -m evals.live_dryrun     # -> evals/live_dryrun.json
```

It needs **no API key and no quota**: `TAVILY_DRY_RUN=true` is an isolated path that forces a sentinel client (never constructs `AsyncTavilyClient`), records the 12 queries a full run would issue together with their sha256 cache keys, and proves `calls_made=0` with a socket guard plus credential-usage counters. See `docs/LIVE_READINESS.md` for the audit (including the `/models` egress risk and the SDK signature check).

Tavily's published pricing is **1 credit per `basic` search / 2 credits per `advanced` search** (1000 free credits/month). This project defaults to `advanced`, so one full research run is at worst 12 requests ≈ **24 credits per company** without cache — an estimate, not a measured charge; the dry-run itself spent **0 credits**. Real measurement (S8.2+) is deliberately blocked until the API keys and quota are explicitly approved.

## Prerequisites

The reworked graph and all entry points need **no API key** in `fixture` mode.
The React UI / OpenRouter / Google Maps / MongoDB items below are **upstream leftovers**;
`/research` now runs the new graph and does not consume a request-body API key.

**Upstream endpoints are left untouched** (plan §9.4): `GET /models` still fetches OpenRouter's
public model list over the network when the UI opens the model picker, and `GET /config` reads
process environment variables. Neither is part of this fork's graph or quota guard. The claim
"zero external calls" applies to the reworked graph, `/research` and the Studio entry only —
verified by socket-level guards in `tests/test_s5_offline.py`.

- Python 3.11 (`.python-version`; the reworked graph and its tests are pinned to 3.11)
- Node.js 18 or later — only for the upstream React UI
- `TAVILY_API_KEY` — **optional, and deliberately hard to spend**: set it at OS user level, not in `.env`. Real calls additionally require `APP_MODE=live`, `TAVILY_LIVE_ENABLED=true` and `TAVILY_MAX_CALLS>0`; see `docs/ACTION_PLAN.md` §9.2. This project has made **0 live calls** so far.
- A model key (OpenRouter / OpenAI / Gemini) — only for `live`; none is configured in this workspace. With `APP_MODE=live` and no model key, `build_graph()` fails **at construction time** with `MissingLLMCredentials`; to exercise live retrieval alone, also set `FEATURES_STRUCTURED_OUTPUT=false`.
- `TAVILY_MAX_CALLS` is a **per-run** budget: each `/research` request builds its own graph and `CallBudget`, while the Studio entry holds one process-wide instance. Real-call accounting must be read from `CallBudget.calls_made`, not inferred from the config value.
- Google Maps / MongoDB — upstream UI features only; not used by the new graph.

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
