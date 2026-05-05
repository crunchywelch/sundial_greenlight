-- Greenlight Database Schema
-- Complete schema definition for audio cable QC and inventory management

-- ============================================================================
-- TABLES
-- ============================================================================

-- Cable SKUs table - all cable variants (catalog, MISC, LTD).
-- Stores only the irreducible per-SKU state. Series, construction fields,
-- color/pattern, and connector type are derived from the SKU + YAML config
-- (util/product_lines/*.yaml) at read time. See greenlight/cable_config.py
-- and shopify_app/app/cable-config.server.js for the resolver.
--
-- length is NULL for catalog SKUs (where the length token lives in the SKU
-- string itself, e.g. "SC-12GL" → 12ft) and required for MISC/LTD variants
-- (where the SKU does not encode length). The CHECK constraint enforces
-- this structurally.
--
-- See docs/CABLE_VARIANTS_REFACTOR.md for the full design rationale.
CREATE TABLE IF NOT EXISTS cable_skus (
    sku TEXT PRIMARY KEY,
    description TEXT,
    length NUMERIC(5,2),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT length_required_for_variants CHECK (
        length IS NOT NULL
        OR NOT (sku ~ '-(MISC-[0-9]+|LTD-[A-Z0-9]{4,12})$')
    )
);

-- Audio cables table - Production records
CREATE TABLE IF NOT EXISTS audio_cables (
    serial_number TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
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
    FOREIGN KEY (sku) REFERENCES cable_skus(sku)
);

CREATE INDEX IF NOT EXISTS idx_audio_cables_order_gid ON audio_cables(shopify_order_gid);

-- LTD (Limited Edition) cable metadata sidecar.
-- One row per LTD edition cable_skus row (sku pattern: {prefix}-LTD-{slug}).
-- CRUD lives in the Shopify app; greenlight is read-only on this table.
-- archived_at IS NULL means the edition is active.
CREATE TABLE IF NOT EXISTS cable_ltd_metadata (
    sku TEXT PRIMARY KEY REFERENCES cable_skus(sku) ON DELETE CASCADE,
    event_name TEXT NOT NULL,
    archived_at TIMESTAMPTZ,
    created_by TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ltd_metadata_active
    ON cable_ltd_metadata(archived_at) WHERE archived_at IS NULL;

-- ============================================================================
-- SEQUENCES
-- ============================================================================

-- Generates the {seq} portion of MISC variant SKUs ({prefix}-MISC-{seq}).
-- See greenlight.db.get_or_create_misc_sku for usage.
CREATE SEQUENCE IF NOT EXISTS cable_misc_variant_seq;
