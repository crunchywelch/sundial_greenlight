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
3. You land on the scan hub: scan a cable to look it up or test it, or press
   a key for intake, inventory, orders, registration codes and labels

### Deactivate Virtual Environment

```bash
deactivate
```

## Features

### Cable Intake
Record pre-labelled cables against a SKU (press `r` at the scan hub):
1. Choose cable type (series → pattern → length → connector, or MISC/LTD)
2. Scan barcode with Zebra DS2208 scanner
3. Confirm serial number on screen
4. Press Enter to save to database
5. Scanner ready for next cable
6. Type 'q' + Enter to finish and see summary

### Test Cables
Scan a cable at the hub to run QC tests:
- Arduino-based electrical testing (continuity, resistance, XLR shell bond)
- Automatic pass/fail determination
- Results saved to database

### Other Features
- **Inventory** dashboard, LTD editions, dealer stock
- **Orders**: customer lookup and order fulfillment
- **Wholesale** registration codes, wire labels, box/UPC labels

## Repository Layout

| Path | What lives there |
|---|---|
| `greenlight/` | The terminal app |
| `shopify_app/` | Shopify Remix app + extensions |
| `catalog/` | Hand-edited product catalog YAML (the source of truth) |
| `data/` | Generated output and vendor input files |
| `tools/` | Admin and back-office scripts, grouped by area |
| `tests/` | SKU parity test + fixtures; `integration/` hits live services |
| `services/` | systemd units |
| `arduino/`, `ArduinoApps/` | Cable tester firmware and hardware docs |

## Testing

```bash
pytest                               # Python tests, no DB or network needed
(cd shopify_app && npm test)         # JS resolver against the same fixtures
```

Scripts in `tests/integration/` write to the live database / Shopify, so
pytest skips them unless `GREENLIGHT_RUN_INTEGRATION=1` is set. Read them
before running.

## Testing the Scanner

```bash
python tools/scanner/scantest.py
```

## Database Setup

See `tools/audio/schema.sql` for the database schema.

## Configuration

Edit `.env` for database settings and hardware flags (`GREENLIGHT_*`).
Operators are listed in `greenlight/config.py`.
