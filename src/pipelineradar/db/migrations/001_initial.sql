-- PipelineRadar initial schema
-- Apply via the Supabase SQL editor or psql before running --dry-run.

create extension if not exists "pgcrypto";

-- ── Enums ─────────────────────────────────────────────────────────────────────

create type entity_kind as enum ('drug', 'company', 'target', 'indication');
create type item_type   as enum ('clinical_trial', 'drug_approval', 'publication');
create type run_status  as enum ('running', 'completed', 'failed');

-- ── entities ──────────────────────────────────────────────────────────────────
-- Canonical registry: every drug/company/target/indication has exactly one row.
-- Aliases and external IDs (NCT, ChEMBL, etc.) live in JSONB columns so we can
-- add new ID namespaces without schema changes.

create table entities (
    id             uuid        primary key default gen_random_uuid(),
    kind           entity_kind not null,
    canonical_name text        not null,
    aliases        jsonb       not null default '[]',
    external_ids   jsonb       not null default '{}',
    created_at     timestamptz not null default now()
);

create index entities_canonical_name on entities (canonical_name);

-- ── runs ──────────────────────────────────────────────────────────────────────
-- One row per pipeline execution. Used to compute "since last run" windows and
-- to track overall pipeline health.

create table runs (
    id          uuid       primary key default gen_random_uuid(),
    started_at  timestamptz not null default now(),
    finished_at timestamptz,
    status      run_status  not null default 'running',
    items_seen  int         not null default 0,
    items_new   int         not null default 0
);

-- ── items ─────────────────────────────────────────────────────────────────────
-- Every normalized record ever ingested. (source, source_id) is the dedup key;
-- content_hash drives change detection — a re-ingested item with a changed hash
-- is treated as new.

create table items (
    id           uuid      primary key default gen_random_uuid(),
    source       text      not null,
    source_id    text      not null,
    item_type    item_type not null,
    title        text      not null,
    summary      text      not null default '',
    url          text      not null default '',
    entity_ids   uuid[]    not null default '{}',
    raw          jsonb     not null default '{}',
    published_at timestamptz,
    ingested_at  timestamptz not null default now(),
    content_hash text      not null,

    constraint items_source_source_id unique (source, source_id)
);

create index items_ingested_at   on items (ingested_at);
create index items_content_hash  on items (content_hash);

-- ── briefs ────────────────────────────────────────────────────────────────────
-- Generated intelligence briefs. One brief per therapeutic area per run.
-- Kept for history so the scheduler can show "last brief for oncology was …".

create table briefs (
    id                uuid        primary key default gen_random_uuid(),
    run_id            uuid        not null references runs (id) on delete cascade,
    therapeutic_area  text        not null,
    body_md           text        not null,
    citations         jsonb       not null default '[]',
    created_at        timestamptz not null default now()
);

create index briefs_run_id on briefs (run_id);
create index briefs_created_at on briefs (created_at);
