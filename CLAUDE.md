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
- `tests/` — run `pytest` (no DB needed); the JS suite is `cd shopify_app &&
  npm test`, **on the DO host** where the app runs and `node_modules` lives;
  `integration/` hits live Postgres/Shopify and only runs with
  `GREENLIGHT_RUN_INTEGRATION=1`
- `services/` — systemd units; `arduino/`, `ArduinoApps/` — tester firmware

### Core Components (`greenlight/`)

- **main.py**: Entry point — hardware init, Shopify connection check, starts the `ScreenManager`
- **screen_manager.py**: Stack-based navigation. Each screen's `run()` returns a
  `ScreenResult` (`PUSH`/`POP`/`REPLACE`/`EXIT`) plus a context dict; no nested loops
- **ui.py**: Shared Rich layout (header/body/footer) used by every screen
- **screens/**: one module per area — `main.py` (splash/operator select),
  `cable/` (package: `base.py` lookup/QC, `lookup.py` scan hub,
  `intake_select.py` + `intake_scan.py` intake), `inventory.py`, `orders.py`
  (customer lookup, fulfillment), `registration_codes.py` (`w`: codes for
  cables not on an order), `wire.py` (wire labels),
  `shopify_scan.py`, `settings.py`
- **cable_config.py**: Loads + validates `catalog/` YAML; SKU parse/format
  (mirrored in JS by `shopify_app/app/cable-config.server.js`)
- **product_lines.py**: Back-office economics (price/cost/weight) on top of cable_config
- **cable_catalog.py**: Cable catalog/variant lookups against the DB (UI lives in `screens/cable/`)
- **db.py**: Postgres connection pool and all cable/order/event queries
- **shopify_client.py**: Shopify Admin API (audio store and wire store)
- **gtin.py**, **registration.py**: UPC validation; registration code generation
- **hardware/**: scanner, Arduino cable tester, TSC label printer, GPIO
- **config.py**: Operators, feature flags and `GREENLIGHT_*` env settings
- **log.py**: Central logging (call `setup_logging()` in every entry point)

### Database

PostgreSQL via `psycopg2.pool.SimpleConnectionPool`. Schema: `tools/audio/schema.sql`.
Main tables: `sku_group`, `audio_cables` (one row per physical cable, including
test results and ownership), `cable_events` (audit trail). Back-office/valuation
tables (`products`, `inventory_snapshots`, `vendor_parts`, `wire_cost_params`, ...)
are managed by `tools/sundial_db.py`.

### Configuration

Operators are configured directly in `config.py` (`OPERATORS`, code →
name + Shopify user id). Everything else comes from `.env` with a
`GREENLIGHT_` prefix: `GREENLIGHT_DB_{NAME,USER,PASS,HOST,PORT}`, hardware
flags `GREENLIGHT_USE_REAL_{ARDUINO,SCANNER,PRINTERS,GPIO}`,
`GREENLIGHT_ARDUINO_PORT`, `GREENLIGHT_TSC_PRINTER_IP`, `GREENLIGHT_LOG_LEVEL`.

### Navigation

1. **Splash / operator select** → goes straight to the scan hub
2. **Scan hub** (`ScanCableLookupScreen`): scan a serial to look up/test a cable,
   or use a key — `r` intake, `i` inventory, `w` registration codes (no order), `p` wire
   labels, `s` Shopify scan mode, `f` fulfill order (website and wholesale),
   `l` lookup customer, `c` calibrate tester, `q` logout

### Order fulfillment

`f` → `FulfillOrdersScreen`, which lists **everything outstanding** across
customers, newest first, each row typed **Website** or **Wholesale**. Pick one
and it goes to `OrderFulfillScanScreen`, which does the per-channel job:

- **Website order:** scan each cable; it's checked against the line items
  (SKU and QC) and assigned to the customer. No labels.
- **Wholesale order:** the same scan and checks, but the cable is assigned to
  the **dealer** (`wholesale_company_gid`/`location_gid`) with `shopify_gid`
  left NULL, and its **registration label prints as it is scanned**, since the
  code belongs to that one cable. Rescanning a cable reprints its label. `l`
  then prints the box labels (`OrderLabelPrintScreen`): side + Prop 65 in one
  pass on the 1" roll, UPC on the 2".

Wholesale vs website comes from the buyer (`purchasingEntity` is a
`PurchasingCompany`), not from whether it's a draft — see
`shopify_client.wholesale_buyer()`. **Getting this wrong locks out the end
buyer:** a wholesale cable assigned as retail gets `shopify_gid` set, and
`api.register-cable.jsx` refuses any cable that already has one.

`l` from the list is the customer-first route (`CustomerLookupScreen` →
`CustomerSearchResultsScreen` → `OrderSelectionScreen`), for when you have a
name rather than an order. It lands on the same scan screen, with the same
dealer handling.

> **Wholesale orders are packed paid or unpaid.** The B2B flow creates a
> Shopify *draft* order and emails an invoice; a draft becomes an Order only
> when completed (the buyer paying, or someone completing it in admin). The
> list shows open drafts ("Invoice Sent · not an order yet") so packing doesn't
> wait on payment. Cables scanned against a draft are stored under the
> DraftOrder GID, and when the list loads, `db.relink_order_cables()` moves
> them onto the Order any completed draft became. Completed drafts aren't
> listed themselves; their Order is.

Greenlight never marks anything fulfilled in Shopify. Website orders are
fulfilled when they ship; wholesale ones by hand.

`w` is **registration codes for cables not on an order** — samples, festival
sales and the like. It's in regular use; don't fold it into `f`. Its
cables stay ours and sellable (see `docs/WHOLESALE_ATTRIBUTION.md`). A
cable coded there and later scanned into a wholesale order keeps its code,
and its first scan doesn't print a second label — rescan to reprint.

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

**Test Cables** (from the scan hub):
1. Scan serial number from cable label
2. System looks up cable record in database
3. If not tested yet, run Arduino QC tests (continuity, resistance, and XLR
   shell bond unless the connector finish skips it)
4. Save test results to `audio_cables`

**Key Features**:
- Cables arrive with pre-printed serial labels; the app prints box/UPC and
  wire labels on the TSC printer (see `docs/LABEL_PRINTING.md`)
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
- `tools/printer/print_shelf_label.py --preview` — box-side label, no hardware.

Box labels need **2" × 3" stock**, not the 1" × 3" cable roll: at 203 DPI a
UPC-A only renders at whole-dot module widths, so 2" stock gives 113.7%
magnification (in spec) while 1" is forced to 75.8%, the GS1 thermal-print
floor, with no room for branding. The TE210 has one media path, so batch them.

**A boxed cable wears up to four stickers**, and only one of them is a UPC: the
*front* gets a pre-printed pattern sticker (Goldline, Silverline, ...), the
*back* gets the 2" × 3" `box_label` with the UPC-A, and the *side* gets the
1" × 3" `shelf_label`. The side is the only face visible once boxes are racked
spine-out, so that template leads with length and connector and deliberately
carries **no barcode** — the back's UPC is what a POS scans. Its text comes
from `cable_config.describe_variant()`, pure `catalog/` YAML with no DB or
Shopify, so shelf labels print with the tunnel down.

It prints six rows — `Sundial Audio Studio Series`, the pattern,
`20' Instrument Cable` (the largest), `TS-TS - Canare GS-6`, then the SKU
bottom-right. **There is deliberately no braid description**: the pattern row
says the same thing in one word, and at up to three rows it left only 4 dots
between rows, which read as a wall of text. `describe_variant()` still returns
that copy as `detail` for callers with room — the label doesn't print it. The
brand line uses a
**`retail_family`** field in `cable_lines.yaml` (`Studio`, `Touring`), coarser
than `product_line` on purpose: the boxes are generic, the pattern is a front
sticker, and the spec line already says Instrument or Microphone. Adding a
field there means mirroring it in `shopify_app/app/cable-config-schemas.js`,
whose per-series shape is `additionalProperties: false`.

The cable type and the connector name both come from `RETAIL_CABLE_TYPES`.
The connector row is the *product-facing* pair name, so a right-angle cable
reads `TS-TS Right Angle` and the internal `RA-TS` shorthand never reaches a
label. Nothing on the label restates a default — no row says a mic cable is
XLR male-to-female, because it always is. No inch marks anywhere either: TSPL
can't escape a double quote, so feet use the prime (`20'`). A new series with
a new connector display needs an entry added; the sweep in
`tests/test_shelf_label.py` fails if one is missing, and also renders every
catalog variant to catch text that runs off the label or over its neighbour.

The fourth sticker is the **Prop 65 warning**, on the 1" roll on the box back.
It is NOT merged into the UPC label: `www.P65Warnings.ca.gov` is 22
unbreakable characters, which fits only font `"1"` at ~4.3 pt, under the 6 pt
legal floor. Its own label has no competing text, so the "no smaller than
other consumer information" clause has nothing to bind against either.

**Printing a wholesale order's labels: `f`, pick the order, scan.** Each
cable's registration label prints as it's scanned; `l` from the scan screen
prints the box labels. Wholesale orders may still be Shopify *draft* orders —
`shopify_app/app/b2b.server.js` creates a draft and emails an invoice, never
completing it — and `get_customer_orders()` cannot see a draft, so the `f`
list fetches drafts separately (`get_draft_orders()`). Planning is in
`greenlight/label_batch.py` (no printer, DB or Shopify in it), which groups
jobs by stock so a mixed run costs one roll swap, and knows three label
grains: per variant (UPC, side), per order (Prop 65 — its text says nothing
about the cable), and per cable (registration codes, printed one at a time
by the scan screen as each cable is in hand).

**Scan-loop guard:** serial numbers are purely numeric, so a scanned 12-digit
UPC would otherwise be zero-padded into a bogus serial.
`db.validate_serial_number` rejects anything `gtin.looks_like_gtin12()`
matches; any new serial-entry path should go through it.

### Scanner Operation

The Zebra DS2208 operates as a USB HID keyboard device:
- Appears to the system as a keyboard input device
- When scanning a barcode, it types the characters and presses Enter
- Application uses Rich console.input() to capture this seamlessly
- No special drivers needed - works with standard keyboard input
- Scanner is initialized at application startup
- Both scanned and manually typed serial numbers work identically

The application maintains a shared UI layout (header/body/footer) across all screens using Rich's Layout system.

