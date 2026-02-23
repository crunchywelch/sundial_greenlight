-- Greenlight Database Schema
-- Complete schema definition for audio cable QC and inventory management

-- ============================================================================
-- TABLES
-- ============================================================================

-- Cable SKUs table - Product definitions
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

-- Special baby types table - Stable type definitions for MISC cables
CREATE TABLE IF NOT EXISTS special_baby_types (
    id SERIAL PRIMARY KEY,
    base_sku TEXT NOT NULL REFERENCES cable_skus(sku),
    description TEXT NOT NULL,
    length REAL,
    shopify_sku TEXT UNIQUE,  -- set to "{base_sku}-{id}" after insert
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
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
    special_baby_type_id INTEGER REFERENCES special_baby_types(id),
    FOREIGN KEY (sku) REFERENCES cable_skus(sku)
);

CREATE INDEX IF NOT EXISTS idx_audio_cables_order_gid ON audio_cables(shopify_order_gid);
