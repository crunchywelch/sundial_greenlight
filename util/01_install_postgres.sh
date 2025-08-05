#!/bin/bash

# util/01_install_postgres.sh
# PostgreSQL installation script for Greenlight application

set -e

echo "🐘 Installing PostgreSQL for Greenlight..."

# Detect OS
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux - Ubuntu/Debian
    if command -v apt-get >/dev/null 2>&1; then
        echo "📦 Installing PostgreSQL on Ubuntu/Debian..."
        sudo apt-get update
        sudo apt-get install -y postgresql postgresql-contrib postgresql-client
        
        # Start and enable PostgreSQL
        sudo systemctl start postgresql
        sudo systemctl enable postgresql
        
    elif command -v yum >/dev/null 2>&1; then
        echo "📦 Installing PostgreSQL on RHEL/CentOS..."
        sudo yum install -y postgresql postgresql-server postgresql-contrib
        
        # Initialize and start PostgreSQL
        sudo postgresql-setup initdb
        sudo systemctl start postgresql
        sudo systemctl enable postgresql
        
    elif command -v pacman >/dev/null 2>&1; then
        echo "📦 Installing PostgreSQL on Arch Linux..."
        sudo pacman -S --noconfirm postgresql
        
        # Initialize and start PostgreSQL
        sudo -u postgres initdb -D /var/lib/postgres/data
        sudo systemctl start postgresql
        sudo systemctl enable postgresql
        
    else
        echo "❌ Unsupported Linux distribution. Please install PostgreSQL manually."
        exit 1
    fi
    
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    if command -v brew >/dev/null 2>&1; then
        echo "📦 Installing PostgreSQL on macOS with Homebrew..."
        brew install postgresql@15
        brew services start postgresql@15
    else
        echo "❌ Homebrew not found. Please install Homebrew first or install PostgreSQL manually."
        exit 1
    fi
    
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "❌ Windows detected. Please install PostgreSQL manually from:"
    echo "   https://www.postgresql.org/download/windows/"
    exit 1
    
else
    echo "❌ Unsupported operating system: $OSTYPE"
    echo "Please install PostgreSQL manually for your system."
    exit 1
fi

# Verify installation
echo "🔍 Verifying PostgreSQL installation..."
if command -v psql >/dev/null 2>&1; then
    POSTGRES_VERSION=$(psql --version | head -n1)
    echo "✅ PostgreSQL installed successfully: $POSTGRES_VERSION"
else
    echo "❌ PostgreSQL installation failed or psql not in PATH"
    exit 1
fi

echo ""
echo "🎉 PostgreSQL installation complete!"
echo ""
echo "Next steps:"
echo "1. Run ./util/02_setup_database.sh to create the database and user"
echo "2. Run ./util/03_create_tables.sh to set up the schema"
echo ""
echo "📝 Note: You may need to configure PostgreSQL authentication in pg_hba.conf"
echo "   depending on your system's default configuration."