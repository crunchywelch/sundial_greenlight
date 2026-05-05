-- Phase 2: Add cable_ltd_metadata sidecar table for LTD (Limited Edition) cables
--
-- LTD editions live as cable_skus rows with sku = "{prefix}-LTD-{slug}"
-- (e.g. "SC-LTD-PHISH26"). The sidecar holds metadata that doesn't apply to
-- catalog or MISC variants: event name, active flag, archive timestamp, notes.
--
-- All LTD edition CRUD lives in the Shopify app (Remix); greenlight only
-- reads from this table. See docs/CABLE_VARIANTS_REFACTOR.md § Phase 2.
--
-- HOW TO RUN:
--   psql "$GREENLIGHT_DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f util/audio/migrations/2026_04_30_add_cable_ltd_metadata.sql
--
-- Non-destructive — only adds a new table. Safe to run while the app is up.

BEGIN;

CREATE TABLE IF NOT EXISTS cable_ltd_metadata (
    sku TEXT PRIMARY KEY REFERENCES cable_skus(sku) ON DELETE CASCADE,
    event_name TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    archived_at TIMESTAMPTZ,
    created_by TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ltd_metadata_active
    ON cable_ltd_metadata(active) WHERE active = TRUE;

COMMIT;
