#!/bin/bash

# util/create_tables.sh
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

# Function to run SQL file
run_sql_file() {
    PGPASSWORD="$GREENLIGHT_DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$GREENLIGHT_DB_USER" -d "$GREENLIGHT_DB_NAME" -f "$1"
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
echo "🏗️  Executing schema.sql..."

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run the schema file
if [ ! -f "$SCRIPT_DIR/schema.sql" ]; then
    echo "❌ schema.sql not found at $SCRIPT_DIR/schema.sql"
    exit 1
fi

if ! run_sql_file "$SCRIPT_DIR/schema.sql"; then
    echo "❌ Error executing schema.sql"
    exit 1
fi

echo "✅ Database schema created successfully"

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
echo "1. Run ./util/import_skus.sh to populate cable SKU data"
echo "2. Start the Greenlight application: python -m greenlight.main"
