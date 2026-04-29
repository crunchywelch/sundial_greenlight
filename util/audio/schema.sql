-- Greenlight Database Schema
-- Complete schema definition for audio cable QC and inventory management

-- ============================================================================
-- TABLES
-- ============================================================================

-- Cable SKUs table - all cable variants (catalog and MISC).
-- Every variant has its own row keyed by its SKU. MISC variants follow the
-- pattern {series_prefix}-MISC-{seq} (e.g. "SC-MISC-42") and have a
-- color_pattern of 'Miscellaneous'. Catalog rows use the standard format.
-- See docs/CABLE_VARIANTS_REFACTOR.md.
CREATE TABLE IF NOT EXISTS cable_skus (
    sku TEXT PRIMARY KEY,
    series TEXT NOT NULL,
    core_cable TEXT NOT NULL,
    braid_material TEXT NOT NULL,
    color_pattern TEXT NOT NULL,
    length TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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

-- ============================================================================
-- SEQUENCES
-- ============================================================================

-- Generates the {seq} portion of MISC variant SKUs ({prefix}-MISC-{seq}).
-- See greenlight.db.get_or_create_misc_sku for usage.
CREATE SEQUENCE IF NOT EXISTS cable_misc_variant_seq;
