#!/bin/bash

# util/setup_database.sh
# Complete database setup for Greenlight application

set -e

echo "🚀 Greenlight Database Setup"
echo "=========================="
echo ""

# Check if scripts exist
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS=(
    "01_install_postgres.sh"
    "02_setup_database.sh" 
    "03_create_tables.sh"
    "04_import_skus.sh"
)

for script in "${SCRIPTS[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$script" ]; then
        echo "❌ Missing setup script: $script"
        exit 1
    fi
done

echo "📋 This script will:"
echo "   1. Install PostgreSQL (if needed)"
echo "   2. Create database and user" 
echo "   3. Create database schema"
echo "   4. Import cable SKU data"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Creating example..."
    cat > .env.example << EOF
# Greenlight Database Configuration
GREENLIGHT_DB_NAME=greenlight
GREENLIGHT_DB_USER=greenlight_user
GREENLIGHT_DB_PASS=change_this_password
GREENLIGHT_DB_HOST=127.0.0.1
GREENLIGHT_DB_PORT=5432

# Hardware Configuration (optional)
GREENLIGHT_USE_REAL_ARDUINO=false
GREENLIGHT_USE_REAL_SCANNER=true
GREENLIGHT_USE_REAL_PRINTERS=false
GREENLIGHT_USE_REAL_GPIO=true
GREENLIGHT_ARDUINO_PORT=/dev/ttyUSB0
GREENLIGHT_ARDUINO_BAUDRATE=9600
EOF
    
    echo "📝 Created .env.example with default values."
    echo "Please copy it to .env and update the values:"
    echo "   cp .env.example .env"
    echo ""
    read -p "Press Enter to continue or Ctrl+C to exit..."
fi

# Ask user what they want to do
echo "What would you like to do?"
echo "1. Full setup (install PostgreSQL, create database, create tables, import data)"
echo "2. Database setup only (skip PostgreSQL installation)"
echo "3. Schema setup only (skip PostgreSQL installation and database creation)"
echo "4. Import data only"
echo ""
read -p "Enter your choice (1-4): " choice

case $choice in
    1)
        echo "🔄 Running full setup..."
        "$SCRIPT_DIR/01_install_postgres.sh"
        "$SCRIPT_DIR/02_setup_database.sh"
        "$SCRIPT_DIR/03_create_tables.sh"
        "$SCRIPT_DIR/04_import_skus.sh"
        ;;
    2)
        echo "🔄 Running database setup..."
        "$SCRIPT_DIR/02_setup_database.sh"
        "$SCRIPT_DIR/03_create_tables.sh"
        "$SCRIPT_DIR/04_import_skus.sh"
        ;;
    3)
        echo "🔄 Running schema setup..."
        "$SCRIPT_DIR/03_create_tables.sh"
        "$SCRIPT_DIR/04_import_skus.sh"
        ;;
    4)
        echo "🔄 Importing data only..."
        "$SCRIPT_DIR/04_import_skus.sh"
        ;;
    *)
        echo "❌ Invalid choice. Exiting."
        exit 1
        ;;
esac

echo ""
echo "🎉 Setup complete!"
echo ""
echo "🚦 Next steps:"
echo "1. Activate your virtual environment: source venv/bin/activate"
echo "2. Install dependencies: pip install -r requirements.txt"
echo "3. Run the application: python -m greenlight.main"
echo ""
echo "📚 For more information, see CLAUDE.md"