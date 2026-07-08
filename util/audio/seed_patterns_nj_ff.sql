-- Seed catalog sku_group rows for two new touring (cotton) patterns:
--   NJ = Neon Jungle, FF = Firefly
-- Group SKU == pattern code; description == pattern name (matches the
-- original seven catalog groups). Run once against prod:
--   psql service=greenlight -f util/audio/seed_patterns_nj_ff.sql
-- Idempotent: re-running is a no-op.
INSERT INTO sku_group (sku, description) VALUES
  ('NJ', 'Neon Jungle'),
  ('FF', 'Firefly')
ON CONFLICT (sku) DO NOTHING;
