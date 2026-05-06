-- Phase 4 migration: split sku-group identity from variant SKU identity.
--
-- Before:
--   cable_skus.sku stores variant SKUs ('SC-12GL', 'SC-12GL-R') for catalog
--   plus group SKUs ('SC-MISC-42', 'SC-LTD-PHISH26') for variants.
--   cable_skus.length holds the cable length (numeric, MISC/LTD only).
--   cable_ltd_metadata sidecar holds event_name/archived_at/created_by/notes.
--
-- After:
--   sku_group.sku stores group SKUs ('SC-GL', 'SC-MISC-42', 'SC-LTD-PHISH26').
--   sku_group has only sku, description, archived_at.
--   audio_cables.sku_group references sku_group(sku) (FK).
--   audio_cables.length and audio_cables.connector_code carry per-cable variation.
--   cable_ltd_metadata is dropped — event_name folds into description,
--   archived_at moves onto sku_group.
--
-- Single transaction. Pre-migration parity check
-- (shopify_app/scripts/phase4-pre-migration-check.mjs) must pass before running.
-- See docs/CABLE_VARIANTS_REFACTOR.md § Phase 4 for full design.

BEGIN;

-- 1. Add per-cable variation columns to audio_cables (nullable during transition)
ALTER TABLE audio_cables
  ADD COLUMN length NUMERIC(5,2),
  ADD COLUMN connector_code TEXT;

-- 2. Backfill catalog cables from their variant SKU.
--    Pattern: 'SC-12GL' → length=12, connector_code=''
--             'SC-12GL-R' → length=12, connector_code='-R'
UPDATE audio_cables
SET length = SUBSTRING(sku FROM '^[A-Z]{2,3}-(\d+)[A-Z]{2,3}(-R)?$')::numeric,
    connector_code = CASE WHEN sku ~ '-R$' THEN '-R' ELSE '' END
WHERE sku ~ '^[A-Z]{2,3}-\d+[A-Z]{2,3}(-R)?$';

-- 3. Backfill MISC/LTD cables from cable_skus.length (set in Phase 3.5).
--    All MISC/LTD variants are straight today; future right-angle MISC/LTD
--    would need a different intake flow.
UPDATE audio_cables ac
SET length = cs.length,
    connector_code = ''
FROM cable_skus cs
WHERE ac.sku = cs.sku
  AND ac.sku ~ '-(MISC-\d+|LTD-[A-Z0-9]{4,12})$';

-- 4. Verify: every cable resolved to a non-null length + connector_code.
DO $$
DECLARE
  unresolved INT;
BEGIN
  SELECT COUNT(*) INTO unresolved FROM audio_cables WHERE length IS NULL OR connector_code IS NULL;
  IF unresolved > 0 THEN
    RAISE EXCEPTION 'audio_cables backfill incomplete: % rows still NULL', unresolved;
  END IF;
END $$;

-- 5. Insert catalog group rows derived from existing variant SKUs.
--    'SC-12GL' → group 'SC-GL', 'SC-12GL-R' → group 'SC-GL' too (same group).
--    ON CONFLICT DO NOTHING because multiple variants collapse to one group.
INSERT INTO cable_skus (sku, description)
SELECT DISTINCT
  REGEXP_REPLACE(sku, '^([A-Z]{2,3})-\d+([A-Z]{2,3})(-R)?$', '\1-\2'),
  NULL
FROM cable_skus
WHERE sku ~ '^[A-Z]{2,3}-\d+[A-Z]{2,3}(-R)?$'
ON CONFLICT (sku) DO NOTHING;

-- 6. Repoint audio_cables.sku to the new group SKU. The FK target now exists
--    (step 5 inserted them) so the UPDATE doesn't trip the FK constraint.
UPDATE audio_cables
SET sku = REGEXP_REPLACE(sku, '^([A-Z]{2,3})-\d+([A-Z]{2,3})(-R)?$', '\1-\2')
WHERE sku ~ '^[A-Z]{2,3}-\d+[A-Z]{2,3}(-R)?$';

-- 7. Delete orphaned per-variant catalog rows. No FK target now points at them.
DELETE FROM cable_skus WHERE sku ~ '^[A-Z]{2,3}-\d+[A-Z]{2,3}(-R)?$';

-- 8. Verify: every audio_cables.sku resolves to a still-existing cable_skus row.
DO $$
DECLARE
  orphans INT;
BEGIN
  SELECT COUNT(*) INTO orphans FROM audio_cables ac
    LEFT JOIN cable_skus cs ON cs.sku = ac.sku
    WHERE cs.sku IS NULL;
  IF orphans > 0 THEN
    RAISE EXCEPTION 'audio_cables has % orphaned rows after sku repoint', orphans;
  END IF;
END $$;

-- 9. Add archived_at to cable_skus (LTD archive state moves here from sidecar)
ALTER TABLE cable_skus ADD COLUMN archived_at TIMESTAMPTZ;

-- 10. Fold cable_ltd_metadata into cable_skus.
--     event_name prepends to description ("Phish Summer Tour 2026 — tour-branded scheme").
--     archived_at copies straight across.
UPDATE cable_skus cs
SET description = CASE
      WHEN cs.description IS NOT NULL AND cs.description <> ''
      THEN lm.event_name || ' — ' || cs.description
      ELSE lm.event_name
    END,
    archived_at = lm.archived_at
FROM cable_ltd_metadata lm
WHERE cs.sku = lm.sku;

DROP TABLE cable_ltd_metadata;

-- 11. Drop now-unused columns from cable_skus.
--     The length CHECK constraint (length_required_for_variants) is dropped
--     automatically with the column.
ALTER TABLE cable_skus
  DROP COLUMN length,
  DROP COLUMN created_at,
  DROP COLUMN updated_at;

-- 12. NOT NULL on the new audio_cables columns.
ALTER TABLE audio_cables
  ALTER COLUMN length SET NOT NULL,
  ALTER COLUMN connector_code SET NOT NULL;

-- 13. Rename audio_cables.sku → audio_cables.sku_group.
--     The FK constraint (audio_cables_sku_fkey) tracks the column rename
--     automatically, but we also rename the constraint for clarity.
ALTER TABLE audio_cables RENAME COLUMN sku TO sku_group;
ALTER TABLE audio_cables RENAME CONSTRAINT audio_cables_sku_fkey TO audio_cables_sku_group_fkey;

-- 14. Rename cable_skus → sku_group.
ALTER TABLE cable_skus RENAME TO sku_group;

-- 15. Partial index for active LTD lookups (replaces idx_ltd_metadata_active
--     which was dropped along with the table).
CREATE INDEX idx_active_ltd ON sku_group(archived_at)
  WHERE archived_at IS NULL AND sku ~ '-LTD-[A-Z0-9]{4,12}$';

COMMIT;
