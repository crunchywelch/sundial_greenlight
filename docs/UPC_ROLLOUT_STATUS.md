# UPC Rollout — Status and Next Steps

Working notes for the retail UPC / box label work landed 2026-10-02.
**Delete this file once the rollout is verified and done.** Durable guidance
lives in `CLAUDE.md` § Retail UPCs and Box Labels and in `LABEL_PRINTING.md`.

## Decision log

- **Shopify's variant `barcode` field is the source of truth for UPCs.** No UPC
  column in Postgres. Considered and rejected: a `upc` column on `sku_group`
  (wrong grain — a catalog group is a bare pattern code like `GL` spanning ~21
  trade items), and a `sku_upc` variant-grain table (redundant once Shopify
  already holds the variant row plus the brand/weight/dimension data GS1 Data
  Hub needs).
- **GS1 US Data Hub API deferred.** It's $6,500/yr for the API add-on, and it
  *cannot allocate GTINs* — Draft (no-GTIN) records are explicitly unmanageable
  via API, so you reserve GTINs in the Data Hub UI regardless. It's a
  publishing channel for product attributes, worth revisiting only if a
  retailer demands Verified by GS1 coverage.
- **Box labels need 2" × 3" stock.** At 203 DPI, UPC-A renders only at
  whole-dot module widths: 2" stock → 113.7% magnification (in spec); 1" → 75.8%,
  the GS1 thermal-print floor, with no room for branding. 1.5" fits the barcode
  but leaves no room for text either.

## What was verified without a DB tunnel or Shopify

Check-digit math against real published UPCs; all validation and rejection
paths; normalization of EAN-13-with-leading-zero and 11-digit input; label
geometry across 2"/1.5"/1" stock (magnification, quiet zones, bottom clearance,
text-vs-barcode overlap); `box_label` refusing an invalid GTIN-12; CSV parsing
with GS1 Data Hub headers; all five dedup/conflict guards in the loader; the
other seven label templates still generating; clean compile.

## What is NOT verified

- **Every Shopify code path.** Zero API calls were made. `get_audio_variant_by_sku()`
  and `set_barcode_for_sku()` are written against the same GraphQL shape
  `audio_shopify_price_sync.py` already uses in production, but unexercised.
- **Actual print output.** No printer and no 2" stock were available.

## Next steps, in order

### 1. Confirm the GTIN capacity tier covers the catalog

The catalog matrix from `catalog/*.yaml` is **192 variants** today
(SC 56 + SV 28 + TC 72 + TV 36), before LTD editions, MISC, or cartons. A
100-GTIN GS1 tier is not enough; the 1,000 tier (8-digit company prefix,
3-digit item reference) is the minimum. This can't be fixed retroactively.

### 2. Check Shopify variant coverage BEFORE loading UPCs

This is the step most likely to bite. `set_barcode_for_sku()` writes to an
*existing* Shopify variant — it cannot create one. Expect a gap: the catalog
config defines 192 variants, but prod `audio_cables` only yields 167 distinct
variant SKUs, and the Shopify variant set may be smaller still.

```bash
# Read-only. Needs Shopify only, no DB.
python tools/audio/audio_upc_sync.py --coverage

# Needs DB + Shopify. The "✗ CREATE" column lists variants that exist in
# Postgres with no matching Shopify variant — those must be created first.
python tools/audio/audio_sku_catalog_report.py --std
```

Decide explicitly whether to assign GTINs to variants you haven't built yet.
Reserving the full 192 in Data Hub is fine and arguably tidier (item references
stay aligned with the catalog), but only variants that exist in Shopify can
receive a `barcode`.

### 3. Load the UPCs

```bash
python tools/audio/audio_upc_sync.py upcs.csv          # dry run — read it
python tools/audio/audio_upc_sync.py upcs.csv --fix    # prompts for confirmation
```

A GS1 Data Hub export works unmodified. The loader refuses `--fix` outright if
the dry run found any error, and never overwrites an existing UPC.

### 4. Verify the printer on real stock

```bash
python tools/printer/print_box_label.py SC-20GL --preview        # geometry report
python tools/printer/print_box_label.py SC-20GL --count 1        # one real label
```

Then **scan the printed label with the Zebra DS2208** and confirm the digits
come back matching the UPC in Shopify. That closes the loop on the one thing
pure-Python checks can't cover: whether the TE210's own check-digit arithmetic
agrees with `gtin.check_digit()`. If the rendered digits differ from Shopify,
stop — don't apply labels.

Also confirm the scanner's symbology config: it may report UPC-A as 12 digits
or as EAN-13 with a leading zero. `gtin.normalize_gtin12()` handles both, but
note which one you get.

### 5. Wire the scan-loop guard (done 2026-10-02)

`db.validate_serial_number` now rejects anything `gtin.looks_like_gtin12()`
matches, with a "product UPC, not a cable serial" message. That covers the
intake scan loop (`screens/cable/intake_scan.py`), the scan hub
(`screens/cable/lookup.py`, which also shows the message instead of offering
intake for a bogus serial) and order fulfillment (`screens/orders.py`).
Wholesale batches and customer assignment only look up existing cables, so a
UPC there fails as "not found" and can't create a row. Covered by
`tests/test_serial_validation.py`.

## Still open (needs a decision)

- **Cartons / multipacks.** If cables ship to retail in master cases, each case
  configuration needs its own GTIN, and GS1 wants ITF-14 or GS1-128 on the
  carton rather than UPC-A. No code exists for this.
- **TUI screen.** Box labels are CLI-only. A `BoxLabelScreen` alongside
  `WireLabelScreen` (`greenlight/screens/wire.py` is the pattern) would put it
  in the operator flow.

## Sandbox gotcha, unrelated to this work

`greenlight/log.py:58` builds a `SysLogHandler` over TCP to `localhost:1514`;
with no syslog listener it blocks for minutes. Every `tools/audio/*` script
calls `setup_logging()` at import, so they all hang on a host without it.
Similarly, importing `greenlight.db` opens the connection pool at module
import, so anything touching it times out without the tunnel — which is why
`box_label` imports only `greenlight.gtin`.
