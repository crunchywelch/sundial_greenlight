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

-- Audio cables table - Production records
CREATE TABLE IF NOT EXISTS audio_cables (
    serial_number TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    resistance_ohms REAL,
    capacitance_pf REAL,
    operator TEXT,
    arduino_unit_id INTEGER,
    notes TEXT,
    test_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    shopify_gid TEXT,
    FOREIGN KEY (sku) REFERENCES cable_skus(sku)
);
