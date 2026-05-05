-- Phase 3.5: Drop YAML-derivable columns from cable_skus, normalize length to
-- numeric, drop the redundant cable_ltd_metadata.active flag.
--
-- After this migration:
--   * cable_skus = (sku, description, length NUMERIC(5,2) NULL,
--                   archived_at, created_at, updated_at)
--     — series, core_cable, braid_material, color_pattern, connector_type
--       all gone; consumers resolve them from the SKU + YAML config.
--     — length is NULL for catalog (encoded in SKU), required for MISC/LTD.
--   * cable_ltd_metadata = same as before minus active. archived_at IS NULL
--     replaces the active=true predicate.
--
-- See docs/CABLE_VARIANTS_REFACTOR.md § Phase 3.5 for design rationale.
--
-- BEFORE RUNNING:
--   1. Confirm both apps are deployed on the new code (greenlight at
--      d6adea8c+, shopify_app at 0d50eb8a+).
--   2. Run the pre-migration parity check (separate Python script):
--          PGSERVICE=greenlight python util/audio/pre_migration_parity_check.py
--      Exit code 0 means safe to proceed.
--   3. Take a database backup.
--
-- HOW TO RUN:
--   psql "$GREENLIGHT_DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f util/audio/migrations/2026_05_07_drop_derivable_columns.sql
--
-- The transaction will abort automatically if any verification check fails.

BEGIN;

-- Lock the affected tables to block concurrent writes for the duration.
LOCK TABLE cable_skus IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE cable_ltd_metadata IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE audio_cables IN SHARE ROW EXCLUSIVE MODE;

-- ----------------------------------------------------------------------------
-- Step 1: Length normalization. Add a numeric column, backfill from text, then
--         swap. Variants must end up with numeric length; catalog stays NULL.
-- ----------------------------------------------------------------------------
ALTER TABLE cable_skus ADD COLUMN length_num NUMERIC(5,2);

-- Backfill variants only. Catalog rows keep length_num NULL — their length
-- token lives in the SKU string and is resolved at read time.
UPDATE cable_skus
   SET length_num = length::numeric
 WHERE sku ~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$'
   AND length ~ '^[0-9]+(\.[0-9]+)?$';

-- Verify: every variant has a numeric length now.
DO $$
DECLARE
    bad INT;
BEGIN
    SELECT COUNT(*) INTO bad
    FROM cable_skus
    WHERE sku ~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$'
      AND length_num IS NULL;
    IF bad > 0 THEN
        RAISE EXCEPTION 'Migration aborted: % variant row(s) failed length backfill (text did not parse as numeric)', bad;
    END IF;
    RAISE NOTICE 'Step 1 OK: variant length backfill complete';
END $$;

-- Verify: catalog rows have length_num NULL (we did not backfill them).
DO $$
DECLARE
    leaked INT;
BEGIN
    SELECT COUNT(*) INTO leaked
    FROM cable_skus
    WHERE sku !~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$'
      AND length_num IS NOT NULL;
    IF leaked > 0 THEN
        RAISE EXCEPTION 'Migration aborted: % catalog row(s) unexpectedly have length_num set', leaked;
    END IF;
    RAISE NOTICE 'Step 1 OK: catalog rows correctly have length_num NULL';
END $$;

-- Swap: drop the old text length, rename length_num → length.
ALTER TABLE cable_skus DROP COLUMN length;
ALTER TABLE cable_skus RENAME COLUMN length_num TO length;

-- ----------------------------------------------------------------------------
-- Step 2: Drop derivable columns from cable_skus.
-- ----------------------------------------------------------------------------
ALTER TABLE cable_skus
    DROP COLUMN series,
    DROP COLUMN core_cable,
    DROP COLUMN braid_material,
    DROP COLUMN color_pattern,
    DROP COLUMN connector_type;

-- ----------------------------------------------------------------------------
-- Step 3: Apply CHECK constraint enforcing the length rule structurally.
--         NULL for catalog (length is in SKU), required for MISC/LTD.
-- ----------------------------------------------------------------------------
ALTER TABLE cable_skus
    ADD CONSTRAINT length_required_for_variants
    CHECK (
        length IS NOT NULL
        OR NOT (sku ~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$')
    );

-- Final shape check.
DO $$
DECLARE
    cols TEXT;
BEGIN
    SELECT string_agg(column_name, ', ' ORDER BY ordinal_position)
      INTO cols
      FROM information_schema.columns
     WHERE table_name = 'cable_skus' AND table_schema = 'public';
    RAISE NOTICE 'Step 3 OK: cable_skus columns = %', cols;
END $$;

-- ----------------------------------------------------------------------------
-- Step 4: Drop cable_ltd_metadata.active. The partial index on active was
--         created in 2026_04_30_add_cable_ltd_metadata.sql; rebuild it on
--         archived_at IS NULL so list_ltd_editions(active_only=True) keeps
--         using the index.
-- ----------------------------------------------------------------------------
DROP INDEX IF EXISTS idx_ltd_metadata_active;

ALTER TABLE cable_ltd_metadata DROP COLUMN active;

CREATE INDEX idx_ltd_metadata_active
    ON cable_ltd_metadata(archived_at)
    WHERE archived_at IS NULL;

DO $$
BEGIN
    RAISE NOTICE 'Step 4 OK: cable_ltd_metadata.active dropped, partial index rebuilt on archived_at IS NULL';
END $$;

-- ----------------------------------------------------------------------------
-- Step 5: Final sanity. Every audio_cables row still resolves to a cable_skus
--         row (the FK should already enforce this; belt-and-suspenders).
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    orphans INT;
BEGIN
    SELECT COUNT(*) INTO orphans
      FROM audio_cables ac
      LEFT JOIN cable_skus cs ON ac.sku = cs.sku
     WHERE cs.sku IS NULL;
    IF orphans > 0 THEN
        RAISE EXCEPTION 'Migration aborted: % audio_cables row(s) lost their cable_skus reference', orphans;
    END IF;
    RAISE NOTICE 'Step 5 OK: every audio_cables row resolves to a cable_skus row';
END $$;

COMMIT;

-- ----------------------------------------------------------------------------
-- Post-migration verification (run independently to confirm).
-- ----------------------------------------------------------------------------
-- \d cable_skus           -- expect: sku, description, length, archived_at, created_at, updated_at
-- \d cable_ltd_metadata   -- expect: sku, event_name, archived_at, created_by, notes, created_at
--
-- SELECT COUNT(*) FROM cable_skus
-- WHERE sku ~ '-(MISC-|LTD-)' AND length IS NULL;  -- expect 0
--
-- SELECT COUNT(*) FROM cable_skus
-- WHERE sku !~ '-(MISC-|LTD-)' AND length IS NOT NULL;  -- expect 0 (catalog rows have NULL length)
