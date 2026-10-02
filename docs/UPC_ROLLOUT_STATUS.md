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

### 1–3. GTIN tier, Shopify coverage, UPC load (done 2026-10-02)

All **222** catalog variants in Shopify now carry their UPC
(`audio_upc_sync.py --coverage`: 222/222, 0 missing; the 76 MISC/LTD variants
are excluded by SKU kind). Loaded from a Data Hub export, which needed:

- Data Hub exports GTINs in the 14-digit field (`00` + UPC-A);
  `normalize_gtin12` now strips the `00`.
- Three Electric Houndstooth variants had wrong SKUs in **both** Shopify and
  Data Hub (TV-12EH, TC-15EH, TC-15EH-R carried the 10/20 ft SKUs), so the
  two sources agreed and were both wrong. Caught by checking each SKU against
  its own Data Hub description and Shopify variant options; fixed in both.
  Repeat that cross-check before loading any future batch.

The old "192 variants" figure came from `catalog/cable_lines.yaml`, which was
missing 1' Studio and 12' Touring; fixed 2026-10-02 along with economics.yaml
(prices = Shopify, weights = GS1 gross, costs = cost sheet), all synced to Shopify.

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
