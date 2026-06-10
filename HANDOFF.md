# PipelineRadar — Claude Code Handoff

This is your kickoff doc. It tells you (and Claude Code) exactly how to start, in what order, and what the first session should produce.

## Before you open Claude Code

1. Create the repo and drop in these three files at the root:
   - `CLAUDE.md`
   - `PipelineRadar_Build_Plan.md`
   - `HANDOFF.md` (this file)
2. Have ready:
   - A **Supabase project** (free tier is fine) — URL + service key.
   - An **Anthropic API key** (you already build on the SDK).
   - Optional: an **openFDA API key** (free, raises the daily limit) — fine to skip for now.
3. Decide your **first watchlist**. Keep it tiny for Phase 1. Suggested seed:
   ```yaml
   therapeutic_areas:
     - oncology
   drugs:
     - pembrolizumab
     - nivolumab
   companies:
     - "Merck Sharp & Dohme"
     - "Bristol Myers Squibb"
   targets:
     - PD-1
   ```

## How to run the build

Work **phase by phase** (see the build plan). One Claude Code session per phase is a good rhythm. At the end of each phase, make Claude Code demonstrate the acceptance criterion before you commit and move on. Resist the urge to let it sprint ahead — the value of this project is that each layer actually works on real data.

## First session prompt (paste into Claude Code)

> Read `CLAUDE.md` and `PipelineRadar_Build_Plan.md` in full before doing anything.
>
> We are executing **Phase 0 (Scaffold)** only. Do not implement ingestion, the LLM, or the graph yet.
>
> Produce:
> 1. The repo structure exactly as laid out in CLAUDE.md, with empty/stub modules and docstrings stating each module's responsibility.
> 2. `pyproject.toml` with the stack from CLAUDE.md, managed for `uv`.
> 3. `.env.example` listing every secret (Supabase URL/key, Anthropic key, optional openFDA key, email/SMTP).
> 4. `config.py` that loads env + `config/watchlist.yaml` into typed Pydantic settings.
> 5. `config/watchlist.yaml` seeded with the oncology watchlist from the handoff.
> 6. The Supabase schema as a SQL migration in `db/migrations/` matching the data model in the build plan (`entities`, `items`, `runs`, `briefs`).
> 7. `db/client.py` with a typed Supabase client and a `healthcheck()` query.
> 8. `main.py` supporting `--dry-run`, which loads config and runs `healthcheck()` and exits.
>
> Acceptance criterion: `python -m pipelineradar.main --dry-run` loads config and connects to Supabase with no errors. Set up `ruff` + `mypy` and make the scaffold pass both. Then stop and show me the dry-run output. Do not start Phase 1.

## Subsequent sessions (one line each, after the prior criterion is green)

- **Phase 1:** "Phase 0 criterion is green. Execute Phase 1 (ingestion + normalization) per the build plan. Real API calls, no LLM. Stop at the Phase 1 acceptance criterion and show me normalized row counts plus 5 sample records."
- **Phase 2:** "Execute Phase 2 (entity resolution + change detection). Prove the criterion: a second consecutive run yields items_new = 0, and the same drug from two sources maps to one entities row."
- **Phase 3:** "Execute Phase 3 (synthesis + LangGraph wiring). Prove: a full graph run on real new items emits a markdown brief where every claim has a working source link."
- **Phase 4:** "Execute Phase 4 (delivery + APScheduler + FastAPI /run and /status). Prove it runs unattended and a brief with only-new items lands in the inbox."
- **Phase 5 (optional):** "Execute Phase 5 (React + Vite dashboard: watchlist editor, brief history, per-entity timeline)."
- **Phase 6:** "Execute Phase 6 (faithfulness eval + structured logging + token/latency metrics per run)."

## Guardrails to enforce on Claude Code

- If it tries to mock source API responses in app code, stop it — mocks go in tests only.
- If it imports the Anthropic or Azure SDK outside `llm/provider.py`, have it refactor behind the abstraction.
- If a phase's acceptance criterion isn't demonstrated, it isn't done — don't let it advance.
- Keep the watchlist small until Phase 4; large watchlists burn API limits and tokens during development.

## The interview payoff (what to capture as you go)

- A short screen recording of a brief generating from live data.
- The README architecture diagram.
- One paragraph on your **entity-resolution approach** (rules + LLM disambiguation + cached registry). This is the detail that makes a pharma-analytics interviewer take you seriously — keep notes as you build it so the writeup is honest and specific.
