#!/bin/bash

# util/03_create_tables.sh
# Complete database schema creation for Greenlight application

set -e

echo "🏗️  Creating Greenlight database schema..."

# Load environment variables
if [ -f .env ]; then
    echo "📄 Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "❌ .env file not found. Please run ./util/02_setup_database.sh first"
    exit 1
fi

# Check required environment variables
if [ -z "$GREENLIGHT_DB_NAME" ] || [ -z "$GREENLIGHT_DB_USER" ] || [ -z "$GREENLIGHT_DB_PASS" ]; then
    echo "❌ Missing required environment variables"
    exit 1
fi

# Set defaults
DB_HOST=${GREENLIGHT_DB_HOST:-127.0.0.1}
DB_PORT=${GREENLIGHT_DB_PORT:-5432}

# Function to run SQL as the greenlight user
run_sql() {
    PGPASSWORD="$GREENLIGHT_DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$GREENLIGHT_DB_USER" -d "$GREENLIGHT_DB_NAME" -c "$1"
}

# Test connection
echo "🧪 Testing database connection..."
if ! run_sql "SELECT version();" >/dev/null 2>&1; then
    echo "❌ Cannot connect to database. Please check your configuration."
    echo "Make sure you've run ./util/02_setup_database.sh first."
    exit 1
fi
echo "✅ Connected to database"

echo ""
echo "🎯 Creating custom enum types..."

# Create custom enum types
run_sql "
    DO \$\$
    BEGIN
        -- Series enum
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'series') THEN
            CREATE TYPE series AS ENUM ('Studio Classic', 'Tour Classic', 'Studio Patch');
        END IF;
        
        -- Color pattern enum
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'color_pattern') THEN
            CREATE TYPE color_pattern AS ENUM ('Black', 'Oxblood', 'Cream', 'Vintage Tweed', 'Road Stripe');
        END IF;
        
        -- Connector type enum
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'connector_type') THEN
            CREATE TYPE connector_type AS ENUM ('TS-TS', 'RA-TS', 'TRS-TRS', 'RTRS-TRS', 'XLR');
        END IF;
        
        -- Length enum
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'length') THEN
            CREATE TYPE length AS ENUM ('0.5', '3', '6', '10', '15', '20');
        END IF;
        
        -- Braid material enum
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'braid_material') THEN
            CREATE TYPE braid_material AS ENUM ('Cotton', 'Rayon');
        END IF;
        
        -- Core cable type enum
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'core_cable_type') THEN
            CREATE TYPE core_cable_type AS ENUM ('Canare GS-6');
        END IF;
    END\$\$;
"

echo "✅ Custom enum types created"

echo ""
echo "📋 Creating cable_skus table..."

# Create cable_skus table
run_sql "
    CREATE TABLE IF NOT EXISTS cable_skus (
        sku TEXT PRIMARY KEY,
        series series NOT NULL,
        price NUMERIC(10, 2),
        core_cable core_cable_type NOT NULL,
        braid_material braid_material NOT NULL,
        color_pattern color_pattern NOT NULL,
        length length NOT NULL,
        connector_type connector_type NOT NULL,
        description TEXT,
        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
    );
"

echo "✅ cable_skus table created"

echo ""
echo "🔢 Creating audio cable sequence..."

# Create sequence for audio cable serial numbers
run_sql "CREATE SEQUENCE IF NOT EXISTS audio_cable_serial_seq START 1;"

echo "✅ Audio cable sequence created"

echo ""
echo "🎵 Creating audio_cables table..."

# Create audio_cables table
run_sql "
    CREATE TABLE IF NOT EXISTS audio_cables (
        serial_number TEXT PRIMARY KEY,
        sku TEXT NOT NULL,
        resistance_ohms REAL,
        capacitance_pf REAL,
        operator TEXT,
        arduino_unit_id INTEGER,
        notes TEXT,
        test_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY (sku) REFERENCES cable_skus(sku)
    );
"

echo "✅ audio_cables table created"

echo ""
echo "🧪 Creating test_results table..."

# Create test_results table for detailed test data
run_sql "
    CREATE TABLE IF NOT EXISTS test_results (
        id SERIAL PRIMARY KEY,
        cable_serial TEXT NOT NULL,
        test_type TEXT NOT NULL,
        test_value REAL,
        test_unit TEXT,
        passed BOOLEAN,
        test_timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
        arduino_unit_id INTEGER,
        notes TEXT,
        
        FOREIGN KEY (cable_serial) REFERENCES audio_cables(serial_number)
    );
"

echo "✅ test_results table created"

echo ""
echo "📊 Creating database indexes..."

# Create indexes for better performance
run_sql "
    -- Cable SKUs indexes
    CREATE INDEX IF NOT EXISTS idx_cable_skus_series ON cable_skus(series);
    CREATE INDEX IF NOT EXISTS idx_cable_skus_connector_type ON cable_skus(connector_type);
    CREATE INDEX IF NOT EXISTS idx_cable_skus_length ON cable_skus(length);
    
    -- Audio cables indexes
    CREATE INDEX IF NOT EXISTS idx_audio_cables_sku ON audio_cables(sku);
    CREATE INDEX IF NOT EXISTS idx_audio_cables_operator ON audio_cables(operator);
    CREATE INDEX IF NOT EXISTS idx_audio_cables_timestamp ON audio_cables(test_timestamp);
    CREATE INDEX IF NOT EXISTS idx_audio_cables_arduino_unit ON audio_cables(arduino_unit_id);
    
    -- Test results indexes
    CREATE INDEX IF NOT EXISTS idx_test_results_cable_serial ON test_results(cable_serial);
    CREATE INDEX IF NOT EXISTS idx_test_results_test_type ON test_results(test_type);
    CREATE INDEX IF NOT EXISTS idx_test_results_timestamp ON test_results(test_timestamp);
    CREATE INDEX IF NOT EXISTS idx_test_results_arduino_unit ON test_results(arduino_unit_id);
"

echo "✅ Database indexes created"

echo ""
echo "🔄 Creating update trigger for cable_skus..."

# Create update trigger for cable_skus
run_sql "
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS \$\$
    BEGIN
        NEW.updated_at = CURRENT_TIMESTAMP;
        RETURN NEW;
    END;
    \$\$ language 'plpgsql';
    
    DROP TRIGGER IF EXISTS update_cable_skus_updated_at ON cable_skus;
    CREATE TRIGGER update_cable_skus_updated_at
        BEFORE UPDATE ON cable_skus
        FOR EACH ROW
        EXECUTE FUNCTION update_updated_at_column();
"

echo "✅ Update trigger created"

echo ""
echo "📋 Database schema summary:"
echo "   ✅ Custom enum types (series, color_pattern, connector_type, length, braid_material, core_cable_type)"
echo "   ✅ cable_skus table with product information"
echo "   ✅ audio_cables table for production records"
echo "   ✅ test_results table for detailed test data"
echo "   ✅ Performance indexes on key columns"
echo "   ✅ Update triggers for timestamps"
echo ""
echo "🎉 Database schema creation complete!"
echo ""
echo "Next steps:"
echo "1. Run ./util/04_import_skus.sh to populate cable SKU data"
echo "2. Start the Greenlight application: python -m greenlight.main"