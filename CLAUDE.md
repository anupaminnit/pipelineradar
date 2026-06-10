# CLAUDE.md — PipelineRadar

Context for Claude Code working in this repo. Read fully before writing code.

## What this is

PipelineRadar is an **autonomous competitive-intelligence agent for life sciences**. On a schedule, it ingests public clinical-trial / drug-approval / literature data for a configured watchlist, resolves entities across sources, detects what is new since the last run, synthesizes a per-therapeutic-area brief, and delivers it. It is a scheduled, stateful, multi-agent system — not a request/response chatbot.

## Golden rules

- **Phased build.** Follow `PipelineRadar_Build_Plan.md`. Do not start a phase before the previous phase's acceptance criterion passes. Confirm the criterion explicitly before moving on.
- **Real data only.** No mocked source responses in app code. Mocks belong in tests (`respx`). The whole point is that it runs on live public APIs.
- **Typed boundaries.** Every value crossing a module boundary is a Pydantic v2 model. No untyped dicts in function signatures.
- **Deterministic where possible.** Normalization, change detection, and content hashing are plain Python — never an LLM. The LLM is used only for synthesis and for entity-disambiguation fallback.
- **Graceful degradation.** One source API failing must not abort the run. Catch, log, note the gap in the brief, continue.
- **Ask before scope creep.** If a requirement is ambiguous, propose the smallest correct version and ask — do not invent features.

## Architecture (summary; full detail in build plan)

LangGraph stateful graph:
`ingest_clinicaltrials | ingest_openfda | ingest_europepmc` (concurrent)
→ `normalize` → `resolve_entities` → `detect_changes`
→ (conditional: skip if no new items) → `synthesize_brief` → `ground_citations` → `deliver`

State persists to Supabase: `entities`, `items`, `runs`, `briefs`. An item is *new* iff `(source, source_id)` is unseen or its `content_hash` changed.

## Tech stack & conventions

- Python 3.11+, dependency mgmt via `uv`.
- `httpx.AsyncClient` for all source calls; every source client has retry + exponential backoff and a typed error.
- LLM access **only** through `src/pipelineradar/llm/provider.py`. Default provider: Anthropic SDK (Claude). Azure OpenAI must remain a single-line swap — never import an SDK directly in agent code.
- Pydantic v2 for schemas (`src/pipelineradar/schemas.py`).
- Config via `config.py` (env + `config/watchlist.yaml`); secrets via `.env`, never hardcoded, never committed.
- Logging: structured (JSON) via `structlog`; one log line per node with `run_id`, node name, duration, item counts.
- Style: `ruff` for lint+format, `mypy` for types. Functions small and single-purpose; prefer pure functions for the deterministic steps.

## Repo layout

```
src/pipelineradar/
  config.py            # env + watchlist loader
  schemas.py           # Pydantic models: Item, Entity, Brief, RunState
  llm/provider.py      # LLM abstraction (Claude default, Azure swappable)
  db/client.py         # Supabase client + typed queries
  db/migrations/       # SQL schema
  ingest/base.py       # shared async client w/ retry
  ingest/clinicaltrials.py
  ingest/openfda.py
  ingest/europepmc.py
  resolve/entity_resolver.py
  detect/change_detector.py
  synthesize/brief_agent.py
  synthesize/prompts.py
  deliver/email.py
  deliver/markdown.py
  graph/state.py       # LangGraph state TypedDict/model
  graph/nodes.py       # node functions
  graph/build_graph.py # graph wiring
  scheduler.py         # APScheduler loop
  api.py               # FastAPI: /run, /status
  main.py              # entrypoint
tests/
config/watchlist.yaml
```

## Commands

```bash
uv sync                                  # install deps
cp .env.example .env                     # then fill secrets
python -m pipelineradar.main --dry-run   # config + DB check, no fetching
python -m pipelineradar.main --once      # single full run now
uvicorn pipelineradar.api:app --reload   # API + manual trigger
pytest                                   # tests
ruff check . && mypy src                 # lint + types (run before declaring a phase done)
```

## Data sources (verify exact params live; they drift)

- **ClinicalTrials.gov v2** — `GET https://clinicaltrials.gov/api/v2/studies`, no auth. Filter watchlist via `query.cond` / `query.intr` / `query.spons`, window with `lastUpdatePostDate`, paginate via `pageToken`.
- **openFDA** — `GET https://api.fda.gov/drug/drugsfda.json`, optional API key (raises daily limit; read from env if present). `search=` query syntax.
- **Europe PMC** — `GET https://www.ebi.ac.uk/europepmc/webservices/rest/search`, no auth, `format=json`, date filter on publication date.

## Definition of done (per change)

Code typed and passing `ruff` + `mypy`; new logic has a test; the relevant phase acceptance criterion in the build plan is demonstrably green; structured logs emitted. State this explicitly when finishing a phase.
