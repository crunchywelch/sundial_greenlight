-- Seed catalog sku_group row for a new studio (rayon) pattern:
--   MB = Midnight Black
-- Group SKU == pattern code; description == pattern name (matches the
-- original seven catalog groups). Run once against prod:
--   psql service=greenlight -f util/audio/seed_patterns_mb.sql
-- Idempotent: re-running is a no-op.
INSERT INTO sku_group (sku, description) VALUES
  ('MB', 'Midnight Black')
ON CONFLICT (sku) DO NOTHING;
