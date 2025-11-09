# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup and Development Commands

```bash
# Setup virtual environment and install dependencies
# IMPORTANT: Must be SOURCED, not executed
source dev_env.sh

# Run the application
python -m greenlight.main

# To deactivate the virtual environment
deactivate
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

1. **Splash screen with operator selection** - Combined screen shows app logo and operator list
2. **Main menu** - Cable QC, Inventory Management, Settings
3. **Cable QC submenu**:
   - Register Cables: Select SKU → Scan cable labels → Register in database
   - Test Cables: Scan serial number → Load from database → Run QC tests

### Cable Workflow

**Register Cables** (Primary workflow):
1. Select cable type:
   - Enter SKU: Choose series → Select from SKU list
   - Select by attributes: Choose series → color → length → connector
2. After selecting cable type, automatically enter scanning mode
3. Scan barcode label using Zebra DS2208 scanner (or press 'm' for manual entry)
4. **Confirmation step**: System displays scanned serial number for verification
5. Press Enter to confirm and save to database (or 'n' to skip, 'q' to quit)
6. System saves cable to database and returns to scanning mode
7. Shows running count and last 5 scanned serial numbers
8. Duplicate detection prevents re-registering existing serial numbers
9. Press 'q' at scan prompt when done to see summary report
10. Supports batch scanning - scan multiple cables of same type in one session

**Test Cables**:
1. Scan serial number from cable label
2. System looks up cable record in database
3. If not tested yet, run Arduino QC tests (resistance, capacitance, continuity)
4. Save test results to database
5. Optionally print QC card with results

**Key Features**:
- No label printing - cables arrive with pre-printed labels
- Scanner-first workflow optimized for rapid data entry
- Real-time feedback on successful scans and errors
- Manual entry fallback if scanner unavailable

### Scanner Operation

The Zebra DS2208 operates as a USB HID keyboard device:
- Appears to the system as a keyboard input device
- When scanning a barcode, it types the characters and presses Enter
- Application uses Rich console.input() to capture this seamlessly
- No special drivers needed - works with standard keyboard input
- Scanner is initialized at application startup
- Both scanned and manually typed serial numbers work identically

The application maintains a shared UI layout (header/body/footer) across all screens using Rich's Layout system.

