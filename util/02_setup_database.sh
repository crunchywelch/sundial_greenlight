#!/bin/bash

# util/02_setup_database.sh
# Database and user creation script for Greenlight application
# Uses environment variables from .env file

set -e

echo "🔧 Setting up Greenlight database and user..."

# Load environment variables
if [ -f .env ]; then
    echo "📄 Loading environment variables from .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "⚠️  .env file not found. Please create one with the following variables:"
    echo "   GREENLIGHT_DB_NAME=greenlight"
    echo "   GREENLIGHT_DB_USER=greenlight_user"
    echo "   GREENLIGHT_DB_PASS=your_secure_password"
    echo "   GREENLIGHT_DB_HOST=127.0.0.1"
    echo "   GREENLIGHT_DB_PORT=5432"
    exit 1
fi

# Check required environment variables
if [ -z "$GREENLIGHT_DB_NAME" ] || [ -z "$GREENLIGHT_DB_USER" ] || [ -z "$GREENLIGHT_DB_PASS" ]; then
    echo "❌ Missing required environment variables:"
    echo "   GREENLIGHT_DB_NAME, GREENLIGHT_DB_USER, GREENLIGHT_DB_PASS"
    exit 1
fi

# Set defaults
DB_HOST=${GREENLIGHT_DB_HOST:-127.0.0.1}
DB_PORT=${GREENLIGHT_DB_PORT:-5432}

echo "📋 Configuration:"
echo "   Database: $GREENLIGHT_DB_NAME"
echo "   User: $GREENLIGHT_DB_USER"
echo "   Host: $DB_HOST"
echo "   Port: $DB_PORT"
echo ""

# Function to run SQL as postgres user
run_as_postgres() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS with Homebrew - postgres user may not exist, try direct connection
        if psql -h "$DB_HOST" -p "$DB_PORT" -U postgres -c "$1" 2>/dev/null; then
            return 0
        else
            # Try without specifying user (homebrew default)
            psql -h "$DB_HOST" -p "$DB_PORT" -d postgres -c "$1"
        fi
    else
        # Linux - use sudo to switch to postgres user
        sudo -u postgres psql -c "$1"
    fi
}

# Check if PostgreSQL is running
echo "🔍 Checking PostgreSQL connection..."
if ! pg_isready -h "$DB_HOST" -p "$DB_PORT" >/dev/null 2>&1; then
    echo "❌ PostgreSQL is not running or not accessible at $DB_HOST:$DB_PORT"
    echo "Please start PostgreSQL and try again."
    exit 1
fi

echo "✅ PostgreSQL is running"

# Create user if it doesn't exist
echo "👤 Creating database user: $GREENLIGHT_DB_USER"
if run_as_postgres "SELECT 1 FROM pg_user WHERE usename = '$GREENLIGHT_DB_USER';" | grep -q "1 row"; then
    echo "⚠️  User $GREENLIGHT_DB_USER already exists"
else
    run_as_postgres "CREATE USER $GREENLIGHT_DB_USER WITH PASSWORD '$GREENLIGHT_DB_PASS';"
    echo "✅ User $GREENLIGHT_DB_USER created"
fi

# Create database if it doesn't exist
echo "🗄️  Creating database: $GREENLIGHT_DB_NAME"
if run_as_postgres "SELECT 1 FROM pg_database WHERE datname = '$GREENLIGHT_DB_NAME';" | grep -q "1 row"; then
    echo "⚠️  Database $GREENLIGHT_DB_NAME already exists"
else
    run_as_postgres "CREATE DATABASE $GREENLIGHT_DB_NAME OWNER $GREENLIGHT_DB_USER;"
    echo "✅ Database $GREENLIGHT_DB_NAME created"
fi

# Grant necessary privileges
echo "🔐 Granting privileges to $GREENLIGHT_DB_USER..."
run_as_postgres "GRANT ALL PRIVILEGES ON DATABASE $GREENLIGHT_DB_NAME TO $GREENLIGHT_DB_USER;"
run_as_postgres "ALTER USER $GREENLIGHT_DB_USER CREATEDB;" # Allow creating test databases

echo "✅ Privileges granted"

# Test connection with new user
echo "🧪 Testing connection with new user..."
export PGPASSWORD="$GREENLIGHT_DB_PASS"
if psql -h "$DB_HOST" -p "$DB_PORT" -U "$GREENLIGHT_DB_USER" -d "$GREENLIGHT_DB_NAME" -c "SELECT version();" >/dev/null 2>&1; then
    echo "✅ Connection test successful"
else
    echo "❌ Connection test failed"
    echo "Please check your PostgreSQL configuration (pg_hba.conf)"
    exit 1
fi

echo ""
echo "🎉 Database setup complete!"
echo ""
echo "Next steps:"
echo "1. Run ./util/03_create_tables.sh to create the database schema"
echo "2. Run ./util/04_import_skus.sh to populate cable SKU data"
echo ""
echo "🔗 Connection string: postgresql://$GREENLIGHT_DB_USER:*****@$DB_HOST:$DB_PORT/$GREENLIGHT_DB_NAME"