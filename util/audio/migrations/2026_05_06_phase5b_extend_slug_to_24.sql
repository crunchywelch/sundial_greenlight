-- Phase 5b: bump LTD slug max length from 12 to 24 characters.
--
-- Real-world editions (GREENRIVER2026, VINTAGEINTHEVALLEY2026) hit the
-- old 12-char ceiling. New limit comfortably covers any realistic
-- edition name without making variant SKUs unwieldy on labels.
--
-- The slug regex appears in three layers:
--   - JS resolver + editions-shared.js (code change, this commit)
--   - Python resolver (pi-side catch-up)
--   - DB partial index `idx_active_ltd` predicate (this migration)
--
-- The index is the only DB-side artifact that pinned the regex; nothing
-- else references slug length structurally. Drop and recreate.

BEGIN;

DROP INDEX IF EXISTS idx_active_ltd;

CREATE INDEX idx_active_ltd ON sku_group(archived_at)
  WHERE archived_at IS NULL AND sku ~ '^LTD-[A-Z0-9]{4,24}$';

COMMIT;
