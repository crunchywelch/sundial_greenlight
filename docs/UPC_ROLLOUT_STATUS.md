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

## What was NOT verified (now resolved)

Both of these are now verified (2026-10-05), see step 4:

- ~~**Every Shopify code path.**~~ `get_audio_variant_by_sku()` is exercised:
  `print_box_label.py SC-20GL` returns the real UPC and product naming.
  `set_barcode_for_sku()` is still unexercised — the UPCs were loaded before
  it existed. Note one store's credentials are being rejected
  (`[API] Invalid API key or access token` on stderr); the audio store works,
  so it is probably the Wire store, and worth chasing separately.
- ~~**Actual print output.**~~ Printed on 2" x 3" stock and scanned with the
  DS2208; reads back the UPC in Shopify.

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

### 4. Verify the printer on real stock (done 2026-10-05)

**The UPC scans.** A printed `SC-20GL` box label read back `810238920632`,
matching Shopify. That closes the one thing pure-Python checks could not: the
TE210 is handed 11 digits and derives the 12th itself, so its agreeing with
`gtin.check_digit()` validates the whole GTIN chain and all 222 loaded UPCs.

Four defects surfaced on the way, none of which could have been caught without
printing — `box_label` had never been run on hardware:

- **Font widths were wrong.** Every template placed text using the cell widths
  in the TSPL manual. Measured on this printer, fonts `"1"` and `"2"` advance
  2 dots more (10 and 14, not 8 and 12); `"3"`, `"4"` and `"5"` match. A first
  attempt generalised a single font-`"2"` measurement into "cell width + 2",
  which was wrong for three of the five — there is no pattern, so
  `tools/printer/calibrate_media.py --measure` now prints a vertical line at
  each font's predicted end and all five are read off a label. Consequences in
  `box_label`: "SUNDIAL" overlapped the logo by 6 dots, and a 19-character LTD
  SKU ran 18 dots off the right edge.
- **`GAP 2 mm, 2 mm` in every template.** The second parameter is the gap
  OFFSET, which must be 0 for die-cut stock; 2 mm of it shifted every label
  this app has ever printed 16 dots down its stock. Now one constant,
  `TSCLabelPrinter.GAP_MM`. The 2 mm gap itself is right — the printer's
  SELFTEST reports 0.08 in = 2.03 mm.
- **The UPC's human-readable digits were cut off**, which GS1 requires legible.
  `box_label` left 14 dots below them; now `BOX_LABEL_BOTTOM_MARGIN = 55`.
- **The subtitle was unclipped**, straight from Shopify at any length, and
  carried Shopify's en-dashes and smart quotes into fonts that render a
  single-byte codepage.

`tests/test_box_label.py` covers all four. `print_box_label.py --preview` now
checks horizontal bounds and element collisions too: it previously checked
only the barcode band, which is why it reported "All checks passed" on a label
with a 6-dot overlap.

### Calibrating for a stock change

`tools/printer/calibrate_media.py` (new). `printer_setup.sh` is a different
job — it switches a factory-fresh printer from ZPL to TSPL, and its
"calibration" step only sets SIZE and GAP without ever running a sensor
detect.

```bash
python tools/printer/calibrate_media.py              # 2" x 3" box stock
python tools/printer/calibrate_media.py --cable-roll # 1" x 3" cable roll
python tools/printer/calibrate_media.py --measure    # font advance + rulers
```

**Never send `GAP 0,0`** — that is TSPL for continuous media, leaving the
printer no top-of-form to register against, and content then lands tens of
dots off. An early version of this tool did exactly that and took three
`GAPDETECT` passes to recover, because no baseline had been recorded first.
Read `SELFTEST` (which prints the printer's stored config) before changing
media settings, not after. The printer also has a web UI on port 80.

### 4a. Original instructions, kept for reference

```bash
python tools/printer/print_box_label.py SC-20GL --preview        # geometry report
python tools/printer/print_box_label.py SC-20GL --count 1        # one real label
```

Then **scan the printed label with the Zebra DS2208** and confirm the digits
come back matching the UPC in Shopify. That closes the loop on the one thing
pure-Python checks can't cover: whether the TE210's own check-digit arithmetic
agrees with `gtin.check_digit()`. If the rendered digits differ from Shopify,
stop — don't apply labels.

The **shelf label** (box side, 1" x 3" cable roll) was iterated on real stock
2026-10-02..05 and is in its final layout; see `LABEL_PRINTING.md`. The notes
below are superseded. It has no barcode, so there is nothing to
scan-check; what needs eyes is whether the font-"5" length and font-"1"
materials line are actually legible at shelf distance, and whether the fixed
positions look right across a row of boxes:

```bash
python tools/printer/print_shelf_label.py SC-20GL --preview
python tools/printer/print_shelf_label.py SC-20GL --count 1
python tools/printer/print_shelf_label.py TV-12NJ --count 1   # 2-line detail
```

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

- **GS1 "short description" on the box label.** Currently the label prints
  Shopify's product title + variant title. Deferred 2026-10-05: printing the
  GS1 short description instead would need somewhere for it to live, and the
  options (generate it from `catalog/`, a Shopify variant metafield, or a
  committed Data Hub CSV) trade off against the no-second-home rule in the
  decision log above. Nothing in the repo holds those strings today — the UPC
  loader only ever read the SKU and GTIN columns.
- **Label stock feed reliability.** The 2" x 3" roll fed erratically during
  verification. Separate from the `GAP 0,0` bug above, which is fixed. If it
  recurs: check the media guides are snug (3" stock that wanders laterally
  drifts off the gap sensor intermittently), and confirm the stock is
  gap-sensed die-cut rather than black-mark or continuous, which need
  `BLINEDETECT` or continuous mode respectively.

- **Cartons / multipacks.** If cables ship to retail in master cases, each case
  configuration needs its own GTIN, and GS1 wants ITF-14 or GS1-128 on the
  carton rather than UPC-A. No code exists for this.
- **TUI screen.** Box labels are CLI-only. A `BoxLabelScreen` alongside
  `WireLabelScreen` (`greenlight/screens/wire.py` is the pattern) would put it
  in the operator flow.

## Roadmap: printing a wholesale order

Orders arrive as Shopify orders — entered by us, or placed by the customer
through the existing Shopify wholesale app. `get_customer_orders()` already
returns line items with `sku` and `quantity`, so the data path exists.

Per retail-boxed cable: the **side label** (`shelf_label`), the **UPC back
label** (`box_label`), and the **registration code label**. The pattern
sticker on the front is pre-printed and not Greenlight's job.

**Phase 1 — done 2026-10-05.** `PrintJob.quantity` is honoured by every
template; `LABEL_STOCK` declares each template's stock; one `TEMPLATES`
dispatch table shared by the real printer and the mock. See
`LABEL_PRINTING.md` § Printing a batch.

**Phase 2 — done 2026-10-05, as a CLI.** `tools/printer/print_order_labels.py`
plans and prints a draft order's retail labels; `greenlight/label_batch.py`
holds the planning. Verified end to end against real draft orders: `#D14` (24
cables over 6 SKUs) plans 48 labels as 12 jobs with one roll swap, and `#D3`
printed. Draft-order support added to `shopify_client` — the B2B flow never
completes its drafts, so `get_customer_orders()` could not see a wholesale
order at all. Still CLI-only; a TUI screen is the remaining piece.

**Phase 3 — a second printer**, one per stock size. Not bought yet, so this is
a note rather than a plan. The shape: a second `GREENLIGHT_TSC_*_PRINTER_IP`,
printers registered in `HardwareManager` **by the stock they have loaded**,
and `get_label_printer(stock)` resolving against that — so a job routes on
what it needs, not on a printer name. With one printer configured, jobs for
absent stock keep today's behaviour of prompting for a roll swap.

### Open: where the Prop 65 warning goes

It needs to be on one of the stickers rather than a fourth. Geometrically
there is room on the 2" x 3" back label: the UPC is centred with 162 dots of
quiet zone each side against the 27 it needs, so shifting it left to x=40
still leaves ~1.5x spec and frees a 237 x 235 dot column beside it.

**The binding constraint is legal, not spatial.** Short-form Prop 65 requires
the warning be at least 6 pt *and* no smaller than the largest type used for
other consumer information on the same label. At 203 DPI font `"1"` is ~4.3 pt
(non-compliant), `"2"` ~7.1 pt, `"3"` ~8.5 pt — and the back label's title is
font `"3"`, so a strict reading of the second clause forces the warning to
font `"3"` too, which fits that column only barely. The existing dedicated
`prop65_label` sidesteps the whole question by having no competing text on it,
which is why it remains the safe default until someone decides how to read
that requirement.

## Sandbox gotcha, unrelated to this work

`greenlight/log.py:58` builds a `SysLogHandler` over TCP to `localhost:1514`;
with no syslog listener it blocks for minutes. Every `tools/audio/*` script
calls `setup_logging()` at import, so they all hang on a host without it.
Similarly, importing `greenlight.db` opens the connection pool at module
import, so anything touching it times out without the tunnel — which is why
`box_label` imports only `greenlight.gtin`.
