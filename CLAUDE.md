# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup and Development Commands

```bash
# Setup virtual environment and install dependencies
./dev_env.sh

# Run the application
python -m greenlight.main
```

## Architecture Overview

**Greenlight** is a terminal-based QC (Quality Control) application for audio cable testing and inventory management. The application uses a PostgreSQL database backend and Rich library for terminal UI.

### Core Components

- **main.py**: Entry point with operator authentication and main application loop
- **ui.py**: Base UI framework using Rich library with layout management (header/body/footer)
- **cable.py**: Cable QC functionality and cable type management
- **inventory.py**: Inventory management interface (placeholder implementation)
- **settings.py**: Settings management interface (placeholder implementation)
- **config.py**: Configuration management with environment variable parsing for operators and database
- **db.py**: PostgreSQL connection pooling and database operations
- **enums.py**: Database enum value fetching utilities

### Database Schema

The application uses PostgreSQL with:
- Connection pooling via psycopg2.pool.SimpleConnectionPool
- Custom ENUM types (cable_type: TS, TRS, XLR)
- Tables: audio_cables, test_results, cable_skus
- Environment-based configuration (GREENLIGHT_DB_*)

### UI Flow Architecture

The current architecture uses nested `while True` loops throughout:
- **main.py:7**: Main application loop
- **ui.py:65,96,123**: Operator menu, main menu, and footer menu loops
- **cable.py:82,111**: Cable selection and QC process loops
- **inventory.py:21** and **settings.py:21**: Module-specific menu loops

### Configuration

Operators are configured directly in `config.py`:
```python
OPERATORS = {
    "ADW": "Aaron Welch",
    "ISS": "Ian Smith", 
    "EDR": "Ed Renauld",
    "SDT": "Sam Tresler",
}
```

Database connection uses standard PostgreSQL environment variables with `GREENLIGHT_` prefix.

### Dependencies

- **rich**: Terminal UI framework for layouts, panels, and styling
- **psycopg2-binary**: PostgreSQL database adapter
- **python-dotenv**: Environment variable management

### Current Menu Structure

1. Splash screen
2. Operator selection (from config)
3. Main menu: Cable QC, Inventory Management, Settings
4. Each module has its own nested menu system

The application maintains a shared UI layout (header/body/footer) across all screens using Rich's Layout system.