# Greenlight Database Utilities

This directory contains database setup and management utilities for the Greenlight application.

## Quick Start

For a complete database setup, run:

```bash
./util/setup_database.sh
```

This interactive script will guide you through the entire setup process.

## Setup Scripts

### 1. PostgreSQL Installation
```bash
./util/01_install_postgres.sh
```
- Installs PostgreSQL on Linux (Ubuntu/Debian, RHEL/CentOS, Arch) or macOS
- Starts and enables the PostgreSQL service
- Verifies the installation

### 2. Database and User Setup
```bash
./util/02_setup_database.sh
```
- Creates the Greenlight database and user based on `.env` configuration
- Sets up proper permissions and privileges
- Tests the connection

**Required Environment Variables** (in `.env`):
- `GREENLIGHT_DB_NAME` - Database name (default: greenlight)
- `GREENLIGHT_DB_USER` - Database user (default: greenlight_user) 
- `GREENLIGHT_DB_PASS` - Database password (required)
- `GREENLIGHT_DB_HOST` - Database host (default: 127.0.0.1)
- `GREENLIGHT_DB_PORT` - Database port (default: 5432)

### 3. Schema Creation
```bash
./util/03_create_tables.sh
```
- Creates all custom enum types (series, color_pattern, connector_type, etc.)
- Creates database tables (cable_skus, audio_cables, test_results)
- Sets up indexes for optimal performance
- Creates update triggers for timestamps

### 4. Data Import
```bash
./util/04_import_skus.sh
```
- Imports cable SKU data from `util/cable_skus.csv`
- Handles insert conflicts with upsert logic
- Provides import summary and statistics

## Environment Configuration

Create a `.env` file in the project root with your database configuration:

```env
# Database Configuration
GREENLIGHT_DB_NAME=greenlight
GREENLIGHT_DB_USER=greenlight_user
GREENLIGHT_DB_PASS=your_secure_password
GREENLIGHT_DB_HOST=127.0.0.1
GREENLIGHT_DB_PORT=5432

# Hardware Configuration (optional)
GREENLIGHT_USE_REAL_ARDUINO=false
GREENLIGHT_USE_REAL_SCANNER=true
GREENLIGHT_USE_REAL_PRINTERS=false
GREENLIGHT_USE_REAL_GPIO=true
GREENLIGHT_ARDUINO_PORT=/dev/ttyUSB0
GREENLIGHT_ARDUINO_BAUDRATE=9600
```

## Database Schema

The Greenlight database includes:

### Tables
- **cable_skus** - Product catalog with SKU information, pricing, and specifications
- **audio_cables** - Production records for manufactured cables
- **test_results** - Detailed test data and measurements

### Custom Enum Types
- **series** - Cable series (Studio Classic, Tour Classic, Studio Patch)
- **color_pattern** - Available color patterns (Black, Oxblood, Cream, etc.)
- **connector_type** - Connector configurations (TS-TS, TRS-TRS, XLR, etc.)
- **length** - Standard cable lengths (0.5, 3, 6, 10, 15, 20 feet)
- **braid_material** - Braiding materials (Cotton, Rayon)
- **core_cable_type** - Core cable specifications (Canare GS-6)

## Legacy Scripts

The following Python scripts are deprecated but maintained for compatibility:

- `create_audio_cables_table.py` - Use `03_create_tables.sh` instead
- `import_skus.py` - Use `04_import_skus.sh` instead

## Data Files

- **cable_skus.csv** - Cable SKU data for import
  - Contains product specifications, pricing, and descriptions
  - Used by the import process to populate the database

## Troubleshooting

### Connection Issues
- Verify PostgreSQL is running: `pg_isready -h 127.0.0.1 -p 5432`
- Check your `.env` file configuration
- Ensure the database user has proper permissions

### Permission Errors
- For Linux: The scripts use `sudo -u postgres` for administrative tasks
- For macOS: Homebrew PostgreSQL may require different authentication
- Check `pg_hba.conf` authentication settings if needed
- Make sure you can run `sudo -u postgres psql` successfully

### Authentication Flow
1. **Database creation** (`02_setup_database.sh`): Uses `sudo -u postgres` to create database and user
2. **Schema creation** (`03_create_tables.sh`): Uses the created user credentials from `.env`
3. **Data import** (`04_import_skus.sh`): Uses the created user credentials from `.env`

### Import Errors
- Verify `cable_skus.csv` exists and has the correct format
- Check that all enum values in the CSV match the database enum types
- Review any error messages for specific data issues

## Development

When adding new database setup functionality:

1. Follow the numbered naming convention (`05_new_feature.sh`)
2. Make scripts executable: `chmod +x script_name.sh`
3. Add error handling with `set -e`
4. Include progress indicators and clear output
5. Update this README with new script documentation

For more information about the Greenlight application, see the main `CLAUDE.md` file.