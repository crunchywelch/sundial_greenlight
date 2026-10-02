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

### Repository Layout

- `greenlight/` — the terminal app (Python package)
- `shopify_app/` — the Shopify Remix app + extensions
- `catalog/` — **hand-edited source of truth** (series, patterns, materials;
  `back_office/` holds pricing/cost/weight, wire cost params, tax exclusions).
  Read at runtime by both `greenlight/cable_config.py` and
  `shopify_app/app/cable-config.server.js`.
- `data/` — generated output and vendor inputs only; nothing here is hand-edited config
- `tools/` — admin/back-office CLI scripts by domain (`audio/`, `wire/`,
  `printer/`, `valuation/`, `shopify/`, `scanner/`); shared helper `tools/sundial_db.py`
- `tests/` — `test_sku_parity.py` + `fixtures/` (no DB needed);
  `integration/` scripts hit live Postgres/Shopify
- `services/` — systemd units; `arduino/`, `ArduinoApps/` — tester firmware

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
   - Cable Intake: Select SKU → Scan cable labels → record in database
   - Test Cables: Scan serial number → Load from database → Run QC tests

### Cable Workflow

> **Intake vs registration — two unrelated things.** *Intake* is the production
> step below: recording a physical cable's pre-printed serial against a SKU.
> *Registration* is an end buyer claiming a cable with its `registration_code` at
> sundialaudio.com/register. The code calls the first `intake_scanned_cable` and
> emits `sku_changed`; the second sets `shopify_gid` + `registered_at` and emits
> `registered`. Don't let the words drift back together.

**Cable Intake** (Primary workflow):
1. Select cable type:
   - Enter SKU: Choose series → Select from SKU list
   - Select by attributes: Choose series → color → length → connector
2. After selecting cable type, automatically enter scanning mode
3. Scan barcode label using Zebra DS2208 scanner (or press 'm' for manual entry)
4. **Confirmation step**: System displays scanned serial number for verification
5. Press Enter to confirm and save to database (or 'n' to skip, 'q' to quit)
6. System saves cable to database and returns to scanning mode
7. Shows running count and last 5 scanned serial numbers
8. Duplicate detection prevents re-taking existing serial numbers
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

### Retail UPCs and Box Labels

Cables boxed for retail carry a UPC-A barcode (GTIN-12) issued against our GS1
US company prefix. See `docs/LABEL_PRINTING.md` for the full write-up.

> **Shopify's variant `barcode` field is the source of truth for UPCs.** There
> is deliberately NO UPC column in Postgres. Shopify already holds the
> per-variant row plus the brand/weight/dimension data GS1 Data Hub wants, so a
> second home would only create drift. Don't add one back.

**UPCs are per-variant, and `sku_group` is the wrong grain for them.** A
catalog group SKU is a bare pattern code (`GL`), and one group spans every
series × length × connector built in that pattern — 21 distinct trade items for
`GL` alone. GS1 requires a separate GTIN per length and per connector, so
anything UPC-shaped keys off the *variant* SKU that
`cable_config.format_variant_sku()` produces (`SC-20GL-R`). Variant SKUs are
derived at runtime and are not rows anywhere in Postgres.

Key pieces:
- `greenlight/gtin.py` — check digits, validation, normalization. Pure
  functions, no DB or network, so label printing works with Postgres down.
- `tsc_label_printer._generate_box_label_tspl()` — the `box_label` template.
  TSPL's `UPCA` type takes **11 digits** and computes the check digit itself;
  we store/validate 12 and send 11, making the printer an independent check.
- `shopify_client.get_audio_variant_by_sku()` / `set_barcode_for_sku()`.
  Note `get_product_by_sku()` queries the Sundial **Wire** store and will never
  find an audio SKU — a mistake that fails silently as "not found".
- `tools/audio/audio_upc_sync.py` — CSV → Shopify loader, dry run by default.
- `tools/printer/print_box_label.py --preview` — geometry report, no hardware.

Box labels need **2" × 3" stock**, not the 1" × 3" cable roll: at 203 DPI a
UPC-A only renders at whole-dot module widths, so 2" stock gives 113.7%
magnification (in spec) while 1" is forced to 75.8%, the GS1 thermal-print
floor, with no room for branding. The TE210 has one media path, so batch them.

**Scan-loop hazard:** serial numbers are purely numeric
(`db.validate_serial_number`), so a scanned 12-digit UPC will be accepted and
zero-padded into a bogus serial. `gtin.looks_like_gtin12()` exists to reject
that, but **is not yet wired into the intake scan loops.**

### Scanner Operation

The Zebra DS2208 operates as a USB HID keyboard device:
- Appears to the system as a keyboard input device
- When scanning a barcode, it types the characters and presses Enter
- Application uses Rich console.input() to capture this seamlessly
- No special drivers needed - works with standard keyboard input
- Scanner is initialized at application startup
- Both scanned and manually typed serial numbers work identically

The application maintains a shared UI layout (header/body/footer) across all screens using Rich's Layout system.

