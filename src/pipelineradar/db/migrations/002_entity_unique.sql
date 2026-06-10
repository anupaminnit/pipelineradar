-- Phase 2: add unique constraint so upsert_entity can use get-or-create safely.
-- Apply in Supabase SQL editor before running --once with Phase 2 code.

alter table entities
    add constraint entities_canonical_name_kind_unique
    unique (canonical_name, kind);
