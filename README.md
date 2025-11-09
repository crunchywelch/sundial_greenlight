# Sundial Greenlight

Terminal-based QC (Quality Control) application for audio cable testing and inventory management.

## Quick Start

### Setup Virtual Environment

```bash
# IMPORTANT: Must be SOURCED, not executed!
source dev_env.sh
```

**Why source instead of execute?**
- Running `./dev_env.sh` activates the venv in a subshell that closes immediately
- Sourcing with `source dev_env.sh` activates it in your current shell session

### Run the Application

```bash
python -m greenlight.main
```

On startup:
1. Splash screen displays with operator list
2. Select your operator number
3. Start working - no extra steps!

### Deactivate Virtual Environment

```bash
deactivate
```

## Features

### Register Cables
Select SKU and scan cable labels to register in database:
1. Choose cable type (by SKU or attributes)
2. Scan barcode with Zebra DS2208 scanner
3. Confirm serial number on screen
4. Press Enter to save to database
5. Scanner ready for next cable
6. Type 'q' + Enter to finish and see summary

### Test Cables
Scan registered cables and run QC tests:
- Arduino-based electrical testing (resistance, capacitance, continuity)
- Automatic pass/fail determination
- Results saved to database

### Other Features
- **Inventory Management** - Track cable inventory
- **Settings** - System configuration

## Testing Scanner

Before using the full app, test if your Zebra DS2208 scanner is working:

```bash
# Basic test (simplest)
python test_scanner.py

# Test with Rich console (same as app uses)
python test_scanner_rich.py

# Test the actual scanner class
python test_scanner_hardware.py
```

See [TEST_SCANNER_README.md](TEST_SCANNER_README.md) for detailed troubleshooting.

## Database Setup

See `./util/` directory for database initialization scripts.

## Configuration

Edit `.env` file for database and operator configuration.
