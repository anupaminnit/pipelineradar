# PipelineRadar — Build Plan

**An autonomous competitive-intelligence agent for life sciences.** It wakes on a schedule, scans public clinical-trial, drug-approval, and literature sources for a configured watchlist, resolves the same entities across sources, detects what is genuinely new, and delivers a synthesized intelligence brief — with zero human prompting.

> Portfolio thesis: this is not a chatbot. It is a *scheduled, stateful, multi-source autonomous agent* — which is what "agentic" actually means. The two hard parts (entity resolution across messy sources, and reliable change detection against memory) are the moat that separates this from a weekend RAG demo.

---

## 1. System overview

```
                          ┌─────────────────────────────────────────┐
   watchlist.yaml ───────▶│            LangGraph orchestrator         │
   (drugs, companies,     │                                          │
    targets, TAs)         │  ingest_ct ─┐                            │
                          │  ingest_fda ─┼─▶ normalize ─▶ resolve ─┐  │
                          │  ingest_pmc ─┘                         │  │
                          │                                        ▼  │
                          │              deliver ◀─ synthesize ◀─ detect_changes
                          └───────┬──────────────────────┬────────────┘
                                  │                       │
                            Supabase (Postgres)     Email / Markdown digest
                            • entity registry
                            • seen_items (state)
                            • briefs (history)
```

Ingestion nodes run concurrently. The graph is stateful: a run only emits a brief for items not seen in prior runs, which is what makes the system *autonomous* rather than a re-summarizer.

## 2. Agent graph (LangGraph nodes)

| Node | Type | Responsibility |
|---|---|---|
| `ingest_clinicaltrials` | tool/IO | Fetch studies matching watchlist from ClinicalTrials.gov API v2 since last run |
| `ingest_openfda` | tool/IO | Fetch recent approvals from openFDA `drugsfda` |
| `ingest_europepmc` | tool/IO | Fetch new publications from Europe PMC |
| `normalize` | deterministic | Map every raw record to one canonical `Item` schema |
| `resolve_entities` | hybrid | Map drug/company/target to canonical entities (rules + LLM disambiguation fallback) |
| `detect_changes` | deterministic | Diff against `seen_items`; produce `new_items` only |
| `synthesize_brief` | LLM agent | Write a per-therapeutic-area brief from `new_items` |
| `ground_citations` | LLM/deterministic | Attach a source URL + identifier to every claim |
| `deliver` | tool/IO | Render markdown brief, send email, persist to `briefs` |

Conditional edge: if `detect_changes` yields no `new_items`, short-circuit straight to a "nothing new" log and skip synthesis (saves tokens).

## 3. Data model (Supabase / Postgres)

```sql
-- canonical entities, the backbone of resolution
entities(id, kind, canonical_name, aliases jsonb, external_ids jsonb, created_at)
  -- kind ∈ {drug, company, target, indication}

-- every normalized record we have ever ingested
items(id, source, source_id, item_type, title, summary, url,
      entity_ids uuid[], raw jsonb, published_at, ingested_at, content_hash)
  -- content_hash drives change detection; source_id+source is unique

-- run bookkeeping for "since last run" windows
runs(id, started_at, finished_at, status, items_seen int, items_new int)

-- generated intelligence briefs, kept for history
briefs(id, run_id, therapeutic_area, body_md, citations jsonb, created_at)
```

Change detection = an item is *new* if `(source, source_id)` is unseen **or** its `content_hash` changed since last ingest.

## 4. Data sources (all free, public, no scraping)

| Source | Endpoint | Auth | Notes |
|---|---|---|---|
| ClinicalTrials.gov v2 | `https://clinicaltrials.gov/api/v2/studies` | none | Query by `query.cond`, `query.intr`, `query.spons`; paginate via `pageToken`; filter by `lastUpdatePostDate` |
| openFDA | `https://api.fda.gov/drug/drugsfda.json` | optional key | Key raises daily limit; `search=` syntax; sort by submission date |
| Europe PMC | `https://www.ebi.ac.uk/europepmc/webservices/rest/search` | none | `query=`, `format=json`, date filters via `PUB_YEAR`/`FIRST_PDATE` |

> Claude Code: verify exact query params against live docs at build time — these APIs evolve. Treat the table as intent, not gospel.

## 5. Tech stack

- **Python 3.11+**, managed with `uv` (or `pip` + venv)
- **LangGraph** — orchestration / stateful graph
- **Anthropic SDK (Claude)** as default LLM, behind a thin `llm/provider.py` abstraction so Azure OpenAI is a one-line swap
- **httpx** (async) for all source APIs
- **Pydantic v2** for every schema (no untyped dicts crossing module boundaries)
- **Supabase** (Postgres) for persistence
- **APScheduler** for the autonomous schedule; **FastAPI** for a manual-trigger + status API
- **React + Vite** dashboard — Phase 5, optional
- **pytest** + **respx** (mock httpx) for tests

## 6. Phased roadmap

Each phase ends with a concrete, demoable acceptance criterion. Do not start a phase before the prior one's criterion is green.

### Phase 0 — Scaffold
Repo structure, `pyproject.toml`, `.env.example`, config loader, Supabase schema migration, `watchlist.yaml`.
**Done when:** `python -m pipelineradar.main --dry-run` loads config and connects to the DB with no errors.

### Phase 1 — Ingestion + normalization (the validated pipeline)
Three ingestion clients + the `normalize` step producing canonical `Item`s. Real data, no LLM yet.
**Done when:** a single command pulls live records for a watchlist (e.g. drug = "pembrolizumab") from all three sources and writes normalized `items` rows. Verified by row counts + spot-checking 5 records.

### Phase 2 — Entity resolution + change detection + persistence
Canonical `entities` registry; rule-based normalization with an LLM disambiguation fallback for ambiguous names; `content_hash` change detection.
**Done when:** running ingestion twice in a row yields `items_new = 0` on the second run, and the same drug from two sources maps to one `entities` row.

### Phase 3 — Synthesis + LangGraph orchestration
Wire all nodes into the LangGraph graph; `synthesize_brief` writes a grounded per-TA brief; `ground_citations` attaches sources.
**Done when:** a full graph run on real new items produces a markdown brief where every claim has a working source link.

### Phase 4 — Delivery + autonomous scheduling
Email/markdown delivery; APScheduler loop; FastAPI `/run` (manual trigger) and `/status` endpoints.
**Done when:** the app runs unattended on a schedule and a brief lands in the inbox containing only genuinely new items since the previous run.

### Phase 5 — Dashboard (optional, demo polish)
React + Vite UI: watchlist editor, brief history, per-entity timeline. Strong for live demos and screenshots on the CV.
**Done when:** you can browse past briefs and edit the watchlist from the browser.

### Phase 6 — Evaluation + observability (the senior signal)
Faithfulness check on synthesized briefs (LLM-as-judge against retrieved items), structured logging of every node, token/latency metrics per run.
**Done when:** each run logs a faithfulness score and a cost/latency summary; a brief that hallucinates an item it wasn't given is caught.

## 7. Key technical risks (own these in interviews)

1. **Entity resolution is the hard part.** Pure exact-match misses ("Merck" vs "Merck & Co" vs "MSD"); pure LLM is slow and non-deterministic. The pragmatic answer — rule-based normalization first, LLM only for the ambiguous residue, with results cached in the `entities` registry — is itself a great talking point.
2. **Change detection correctness.** A bug here either spams duplicates or silently drops updates. The `content_hash` + `(source, source_id)` uniqueness invariant must be tested explicitly (Phase 2 acceptance criterion).
3. **API drift & rate limits.** Wrap every source in a client with retry/backoff and a clear error surface; never let one source failing kill the whole run (degrade gracefully, note it in the brief).

## 8. What "done" looks like for the CV

A repo with a clean README + architecture diagram, a live-data demo (GIF or short video of a brief generating), and a one-paragraph writeup of the entity-resolution approach. That last paragraph is what makes an interviewer lean in.
