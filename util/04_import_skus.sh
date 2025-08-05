#!/bin/bash

# util/04_import_skus.sh
# Import cable SKU data from CSV file

set -e

echo "📦 Importing cable SKU data..."

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
CSV_FILE="util/cable_skus.csv"

# Check if CSV file exists
if [ ! -f "$CSV_FILE" ]; then
    echo "❌ CSV file not found: $CSV_FILE"
    echo "Please ensure the cable SKU data file exists."
    exit 1
fi

echo "🧪 Testing database connection..."
if ! PGPASSWORD="$GREENLIGHT_DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$GREENLIGHT_DB_USER" -d "$GREENLIGHT_DB_NAME" -c "SELECT 1;" >/dev/null 2>&1; then
    echo "❌ Cannot connect to database. Please check your configuration."
    echo "Make sure you've run ./util/02_setup_database.sh and ./util/03_create_tables.sh first."
    exit 1
fi
echo "✅ Connected to database"

echo ""
echo "🗂️  Checking CSV file format..."
head -n 3 "$CSV_FILE"

echo ""
echo "📥 Running Python import script..."

# Run the dedicated Python import script
python3 util/import_cable_skus.py

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Cable SKU import complete!"
    echo ""
    echo "Next steps:"
    echo "1. Start the Greenlight application: python -m greenlight.main"
    echo "2. Begin testing cables using the QC interface"
else
    echo ""
    echo "❌ Import failed. Please check the error messages above."
    exit 1
fi