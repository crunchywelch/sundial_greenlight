-- Phase 5 migration: drop the per-series prefix from catalog and LTD
-- sku_group identifiers. Series prefix moves onto audio_cables so a single
-- LTD edition can span multiple cable types.
--
-- Before:
--   catalog group: 'SC-GL', 'SV-GL', 'TC-BU' ... (one per series × pattern)
--   ltd group:     'TC-LTD-LISTONS2026', etc. (one per series × edition)
--   misc group:    'SC-MISC-42' (untouched)
--   audio_cables.{sku_group, length, connector_code}
--
-- After:
--   catalog group: 'GL', 'SL', 'BU' ... (one per pattern)
--   ltd group:     'LTD-LISTONS2026' (one per edition; can span series)
--   misc group:    'SC-MISC-42' (untouched)
--   audio_cables.{sku_group, prefix, length, connector_code}
--
-- The user-facing variant SKU is still series-specific
-- ('SC-12GL', 'SC-LTD-LISTONS2026'), formatted from
-- (audio_cables.prefix, sku_group, length, connector_code).
--
-- Single transaction. Pre-migration parity check
-- (shopify_app/scripts/phase5-pre-migration-check.mjs) must pass first.

BEGIN;

-- 1. Add prefix to audio_cables (nullable during transition).
ALTER TABLE audio_cables ADD COLUMN prefix TEXT;

-- 2. Backfill prefix from current sku_group. Works for all three kinds
--    since each starts with '{prefix}-'.
UPDATE audio_cables
SET prefix = SUBSTRING(sku_group FROM '^([A-Z]{2,3})-');

-- 3. Verify every cable got a prefix.
DO $$
DECLARE
  unresolved INT;
BEGIN
  SELECT COUNT(*) INTO unresolved FROM audio_cables WHERE prefix IS NULL;
  IF unresolved > 0 THEN
    RAISE EXCEPTION 'audio_cables.prefix backfill incomplete: % rows still NULL', unresolved;
  END IF;
END $$;

-- 4. Insert collapsed sku_group rows for catalog (pattern_code only) and
--    LTD (LTD-{slug} only). MISC rows are untouched. ON CONFLICT DO
--    NOTHING because catalog patterns may already collide on collapse
--    (e.g., SC-GL and SV-GL both map to GL).
--
--    For description: take an arbitrary representative — the parity check
--    confirmed no conflicts exist. (If a future run had conflicts, this
--    would need explicit resolution before running.)
INSERT INTO sku_group (sku, description, archived_at)
SELECT DISTINCT ON (REGEXP_REPLACE(sku, '^[A-Z]{2,3}-', ''))
       REGEXP_REPLACE(sku, '^[A-Z]{2,3}-', ''),
       description,
       archived_at
FROM sku_group
WHERE sku ~ '^[A-Z]{2,3}-(LTD-[A-Z0-9]{4,12}|[A-Z]{2,3})$'
ON CONFLICT (sku) DO NOTHING;

-- 5. Repoint audio_cables.sku_group from per-series catalog/LTD groups to
--    the collapsed groups. MISC rows are skipped (they don't match the
--    catalog/LTD shape).
UPDATE audio_cables
SET sku_group = REGEXP_REPLACE(sku_group, '^[A-Z]{2,3}-', '')
WHERE sku_group ~ '^[A-Z]{2,3}-(LTD-[A-Z0-9]{4,12}|[A-Z]{2,3})$';

-- 6. Verify no audio_cables row points at a now-orphaned old group.
DO $$
DECLARE
  orphans INT;
BEGIN
  SELECT COUNT(*) INTO orphans
  FROM audio_cables ac
  LEFT JOIN sku_group sg ON sg.sku = ac.sku_group
  WHERE sg.sku IS NULL;
  IF orphans > 0 THEN
    RAISE EXCEPTION 'audio_cables has % orphaned rows after repoint', orphans;
  END IF;
END $$;

-- 7. Delete the old per-series catalog and LTD rows from sku_group.
--    Nothing references them now (audio_cables points at the collapsed
--    versions; MISC rows don't match this regex).
DELETE FROM sku_group
WHERE sku ~ '^[A-Z]{2,3}-(LTD-[A-Z0-9]{4,12}|[A-Z]{2,3})$';

-- 8. NOT NULL on audio_cables.prefix.
ALTER TABLE audio_cables ALTER COLUMN prefix SET NOT NULL;

-- 9. Update the partial LTD index to match the new SKU shape. The old
--    index used `sku ~ '-LTD-[A-Z0-9]{4,12}$'` which still works post-
--    migration (LTD-PHISH26 still matches), but rebuild for clarity.
DROP INDEX IF EXISTS idx_active_ltd;
CREATE INDEX idx_active_ltd ON sku_group(archived_at)
  WHERE archived_at IS NULL AND sku ~ '^LTD-[A-Z0-9]{4,12}$';

COMMIT;
