-- Phase 1: Unify MISC variants into cable_skus
--
-- Eliminates the special_baby_types table and audio_cables.special_baby_type_id FK.
-- After this migration, every cable variant (catalog + MISC) has a single row
-- in cable_skus with the SKU as PK.
--
-- See docs/CABLE_VARIANTS_REFACTOR.md for full design rationale.
--
-- HOW TO RUN:
--   psql "$GREENLIGHT_DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f util/audio/migrations/2026_04_29_unify_misc_into_cable_skus.sql
--
-- The transaction will abort automatically if any verification check fails.
-- Take a database backup before running.

BEGIN;

-- Prevent concurrent writes to the affected tables for the duration of the
-- migration. SHARE UPDATE EXCLUSIVE blocks DDL and other migrations but allows
-- ordinary SELECTs.
LOCK TABLE special_baby_types IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE audio_cables IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE cable_skus IN SHARE ROW EXCLUSIVE MODE;

-- ----------------------------------------------------------------------------
-- Step 1: Promote each special_baby_types row to a real cable_skus row.
-- The sbt.shopify_sku is already in the format we want as the new PK
-- (e.g. "SC-MISC-42"). Inherit construction fields from the placeholder base
-- SKU; override length and description with the variant's own values.
-- ----------------------------------------------------------------------------
INSERT INTO cable_skus (sku, series, core_cable, braid_material, color_pattern,
                        length, connector_type, description)
SELECT sbt.shopify_sku,
       cs.series,
       cs.core_cable,
       cs.braid_material,
       'Miscellaneous',
       COALESCE(sbt.length::text, cs.length),
       cs.connector_type,
       sbt.description
FROM special_baby_types sbt
JOIN cable_skus cs ON sbt.base_sku = cs.sku
WHERE sbt.shopify_sku IS NOT NULL;

-- Verify: every special_baby_type with a shopify_sku produced a cable_skus row.
DO $$
DECLARE
    sbt_count INT;
    new_misc_count INT;
BEGIN
    SELECT COUNT(*) INTO sbt_count
    FROM special_baby_types WHERE shopify_sku IS NOT NULL;

    SELECT COUNT(*) INTO new_misc_count
    FROM cable_skus WHERE sku ~ '-MISC-[0-9]+$';

    IF sbt_count != new_misc_count THEN
        RAISE EXCEPTION 'MISC variant count mismatch: % special_baby_types vs % new cable_skus rows',
            sbt_count, new_misc_count;
    END IF;
    RAISE NOTICE 'Step 1 OK: promoted % MISC variants to cable_skus', new_misc_count;
END $$;

-- ----------------------------------------------------------------------------
-- Step 2: Repoint audio_cables.sku from the placeholder to the real variant.
-- ----------------------------------------------------------------------------
UPDATE audio_cables ac
SET sku = sbt.shopify_sku
FROM special_baby_types sbt
WHERE ac.special_baby_type_id = sbt.id;

-- Verify: zero cables still pointing at a placeholder SKU.
DO $$
DECLARE
    leftover INT;
BEGIN
    SELECT COUNT(*) INTO leftover
    FROM audio_cables
    WHERE sku IN ('SC-MISC','SP-MISC','SV-MISC','TC-MISC','TV-MISC');

    IF leftover > 0 THEN
        RAISE EXCEPTION 'Migration aborted: % audio_cables rows still reference placeholder SKUs', leftover;
    END IF;

    SELECT COUNT(*) INTO leftover
    FROM audio_cables
    WHERE special_baby_type_id IS NOT NULL
      AND sku !~ '-MISC-[0-9]+$';

    IF leftover > 0 THEN
        RAISE EXCEPTION 'Migration aborted: % rows have special_baby_type_id but sku does not match -MISC-N pattern', leftover;
    END IF;

    RAISE NOTICE 'Step 2 OK: all audio_cables now point at real SKUs';
END $$;

-- ----------------------------------------------------------------------------
-- Step 3: Drop dead infrastructure.
-- ----------------------------------------------------------------------------
ALTER TABLE audio_cables DROP COLUMN special_baby_type_id;
DROP TABLE special_baby_types;
DELETE FROM cable_skus
WHERE sku IN ('SC-MISC','SP-MISC','SV-MISC','TC-MISC','TV-MISC');

-- ----------------------------------------------------------------------------
-- Step 4: Sequence for new MISC variant SKUs going forward.
-- Initialized above the highest existing seq so post-migration inserts don't
-- collide with migrated rows.
-- ----------------------------------------------------------------------------
CREATE SEQUENCE IF NOT EXISTS cable_misc_variant_seq;
SELECT setval(
    'cable_misc_variant_seq',
    GREATEST(
        1,
        (SELECT COALESCE(MAX(SUBSTRING(sku FROM '-MISC-([0-9]+)$')::int), 0)
         FROM cable_skus
         WHERE sku ~ '-MISC-[0-9]+$')
    )
);

-- Final sanity check: every audio_cables row resolves to a valid cable_skus row.
DO $$
DECLARE
    orphans INT;
BEGIN
    SELECT COUNT(*) INTO orphans
    FROM audio_cables ac
    LEFT JOIN cable_skus cs ON ac.sku = cs.sku
    WHERE cs.sku IS NULL;

    IF orphans > 0 THEN
        RAISE EXCEPTION 'Migration aborted: % audio_cables rows have no matching cable_skus row', orphans;
    END IF;
    RAISE NOTICE 'Step 4 OK: all audio_cables resolve to cable_skus';
END $$;

COMMIT;

-- ----------------------------------------------------------------------------
-- Post-migration verification (run independently to confirm)
-- ----------------------------------------------------------------------------
-- SELECT COUNT(*) FROM audio_cables ac
-- LEFT JOIN cable_skus cs ON ac.sku = cs.sku
-- WHERE cs.sku IS NULL;  -- expect 0
--
-- SELECT COUNT(*) FROM cable_skus
-- WHERE sku ~ '-MISC-[0-9]+$' AND (description IS NULL OR length IS NULL);
-- -- expect 0
--
-- SELECT COUNT(*) FROM cable_skus
-- WHERE sku IN ('SC-MISC','SP-MISC','SV-MISC','TC-MISC','TV-MISC');
-- -- expect 0
--
-- SELECT currval('cable_misc_variant_seq');  -- highest existing MISC variant id
