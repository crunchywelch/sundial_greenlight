-- Greenlight Database Schema (Phase 4)
-- Complete schema definition for audio cable QC and inventory management

-- ============================================================================
-- TABLES
-- ============================================================================

-- sku_group — the kind-of-cable identity table.
-- One row per group. Group SKU patterns:
--   catalog: '{prefix}-{pattern_code}'      (e.g. 'SC-GL', 'TC-HP')
--   misc:    '{prefix}-MISC-{seq}'          (e.g. 'SC-MISC-42')
--   ltd:     '{prefix}-LTD-{slug}'          (e.g. 'TC-LTD-PHISH26')
--
-- Series, construction (core_cable, braid_material), connector options, and
-- pattern names are derived from the SKU + the YAML config under
-- util/product_lines/. See greenlight/cable_config.py and
-- shopify_app/app/cable-config.server.js for the resolver.
--
-- description carries:
--   catalog: pattern name (e.g. "Goldline") — seeded via migration (no auto-seed helper)
--   misc:    operator-supplied description ("dark putty houndstooth, gold connectors")
--   ltd:     event_name + optional notes ("Phish Summer Tour 2026")
-- archived_at IS NULL for active groups; soft-delete for retired LTD editions
-- and (eventually) retired catalog patterns.
--
-- See docs/CABLE_VARIANTS_REFACTOR.md § Phase 4 for design rationale.
CREATE TABLE IF NOT EXISTS sku_group (
    sku TEXT PRIMARY KEY,
    description TEXT,
    archived_at TIMESTAMPTZ
);

-- Partial index for active LTD lookups (matches the `list_ltd_editions`
-- predicate `archived_at IS NULL AND sku ~ '-LTD-...'`).
CREATE INDEX IF NOT EXISTS idx_active_ltd ON sku_group(archived_at)
    WHERE archived_at IS NULL AND sku ~ '^LTD-[A-Z0-9]{4,24}$';

-- audio_cables — production records, one row per physical cable.
-- length and connector_code are per-cable: the same sku_group can hold
-- cables of different lengths (especially for MISC/LTD groups).
CREATE TABLE IF NOT EXISTS audio_cables (
    serial_number TEXT PRIMARY KEY,
    sku_group TEXT NOT NULL,
    -- Series prefix ('SC', 'TC'). Lives per-cable because catalog and LTD group
    -- SKUs drop the prefix, and the variant SKU still has to be derivable.
    prefix TEXT NOT NULL,
    length NUMERIC(5,2) NOT NULL,
    connector_code TEXT NOT NULL,
    -- Connector finish (e.g. 'nickel', 'black_gold') for custom/LTD builds.
    -- NULL = standard catalog, infer shell-test behavior from the series.
    connector_finish TEXT,
    operator TEXT,
    arduino_unit_id INTEGER,
    notes TEXT,
    test_timestamp TIMESTAMPTZ,
    shopify_gid TEXT,
    updated_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    resistance_adc INTEGER,
    test_passed BOOLEAN,
    registration_code VARCHAR(9) UNIQUE,
    calibration_adc INTEGER,
    resistance_adc_p3 INTEGER,
    calibration_adc_p3 INTEGER,
    shopify_order_gid TEXT,
    -- Wholesale channel attribution: the B2B dealer that bought this cable.
    -- Distinct from shopify_gid, which is ALWAYS the end owner (written only by
    -- retail order fulfillment or end-buyer registration). A B2B order assignment
    -- writes these two and deliberately leaves shopify_gid NULL, so the end buyer
    -- can still claim the cable via its registration code.
    wholesale_company_gid TEXT,
    wholesale_location_gid TEXT,
    -- When the end buyer registered the cable — the warranty start date.
    -- updated_timestamp can't serve this; any edit clobbers it.
    registered_at TIMESTAMPTZ,
    FOREIGN KEY (sku_group) REFERENCES sku_group(sku)
);

CREATE INDEX IF NOT EXISTS idx_audio_cables_order_gid ON audio_cables(shopify_order_gid);

-- Partial index for dealer rollups ("every cable sold to Mill River Music").
CREATE INDEX IF NOT EXISTS idx_audio_cables_wholesale_company
    ON audio_cables(wholesale_company_gid)
    WHERE wholesale_company_gid IS NOT NULL;

-- cable_events — append-only audit log. Every commercial mutation on
-- audio_cables overwrites in place, so without this there is no way to answer
-- "who cleared this registration code?" or to notice that an assignment
-- silently destroyed dealer attribution.
--
-- `event` is free text rather than an ENUM so Greenlight and the Shopify admin
-- can add event kinds without coordinating a migration. Known values:
--   assigned_customer, unassigned_customer, assigned_dealer, unassigned_dealer,
--   code_generated, code_cleared, registered, sku_changed, qc_tested
--
-- `registered` (the end buyer claimed the cable, written by the public
-- registration endpoint) and `sku_changed` (an operator corrected the cable's
-- SKU/length/connector, what Greenlight's UI calls "re-register") are unrelated
-- events despite the similar-sounding UI wording — hence the distinct names.
--
-- `actor` distinguishes the source: an operator code from Greenlight ('ADW'),
-- 'admin' from the Shopify admin app, or 'buyer' from public registration.
CREATE TABLE IF NOT EXISTS cable_events (
    id BIGSERIAL PRIMARY KEY,
    serial_number TEXT NOT NULL REFERENCES audio_cables(serial_number),
    event TEXT NOT NULL,
    actor TEXT,
    detail JSONB,                -- conventionally {"from": ..., "to": ...}
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cable_events_serial
    ON cable_events(serial_number, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cable_events_created
    ON cable_events(created_at DESC);

-- ============================================================================
-- SEQUENCES
-- ============================================================================

-- Generates the {seq} portion of MISC variant SKUs ({prefix}-MISC-{seq}).
-- See greenlight.db.get_or_create_misc_sku.
CREATE SEQUENCE IF NOT EXISTS cable_misc_variant_seq;
