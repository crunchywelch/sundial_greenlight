# TSC TE210 Label Printer Setup and Usage

This document describes how to set up and use the TSC TE210 thermal transfer label printer for printing cable labels in Greenlight.

## Hardware Setup

### Printer Specifications
- **Model**: TSC TE210 Thermal Transfer Printer
- **Label Size**: 1" x 3" (25.4mm x 76.2mm)
- **Connection**: Network (TCP/IP)
- **Protocol**: TSPL (TSC Printer Language)
- **Resolution**: 203 DPI

### Network Configuration
1. **IP Address**: Default is `192.168.0.52`
2. **Port**: Default is `9100` (raw printing port)
3. Ensure the printer is on the same network as the Greenlight terminal
4. Test connectivity: `ping 192.168.0.52`

## Software Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Enable real printer (set to false for testing with mock printer)
GREENLIGHT_USE_REAL_PRINTERS=true

# TSC Printer network settings
GREENLIGHT_TSC_PRINTER_IP=192.168.0.52
GREENLIGHT_TSC_PRINTER_PORT=9100
```

### Label Dimensions

The label dimensions are configured in `greenlight/config.py`:

```python
TSC_LABEL_WIDTH_MM = 76.2   # 3 inches
TSC_LABEL_HEIGHT_MM = 25.4  # 1 inch
```

## Label Layout

Labels are formatted to match the reference PDF (`SC-20GL.pdf`):

```
+------------------------------------------+
| SUNDIAL AUDIO                            |
| ━━━━━━━━━━━                              |
| Studio Series                            |
| 20' Goldline                             |
| Straight Connectors            SC-20GL   |
+------------------------------------------+
```

For MISC (miscellaneous) cables with custom descriptions:

```
+------------------------------------------+
| SUNDIAL AUDIO                            |
| ━━━━━━━━━━━                              |
| Studio Series                            |
| 15'                                      |
| Custom putty houndstooth                 |
| with gold connectors           SC-MISC   |
+------------------------------------------+
```

## Testing the Printer

### Test with Mock Printer (No Hardware)

```bash
python tools/printer/print_label.py --self-test --mock
```

This will simulate label printing without connecting to actual hardware.

### Test with Real Printer

1. Ensure printer is powered on and connected to network
2. Verify network connectivity: `ping 192.168.0.52`
3. Run the test script:

```bash
python tools/printer/print_label.py --self-test
```

The script will:
- Connect to the printer
- Generate sample labels for different cable types
- Ask for confirmation before printing each label
- Display status and results

## Prop 65 Warning Labels

California Proposition 65 warning labels require the exclamation-point warning
triangle. Since the TE210 only renders built-in bitmap fonts, the triangle is
rasterized as a bitmap by the driver (template `prop65_label`).

```bash
# Preview the triangle + TSPL without printing (recommended first)
python tools/printer/print_prop65.py --preview

# Short-form label (default), naming a chemical
python tools/printer/print_prop65.py --chemical lead

# Full warning statement
python tools/printer/print_prop65.py --form long --chemical DEHP

# Cancer-only endpoint, 10 copies
python tools/printer/print_prop65.py --endpoints cancer --count 10

# Dry-run against the mock printer
python tools/printer/print_prop65.py --mock
```

Options: `--form {short,long}`, `--chemical NAME`,
`--endpoints {both,cancer,reproductive}`, `--count N`, `--preview`, `--mock`.

## Retail Box Labels (UPC-A)

Cables boxed for sale through retail stores carry a box label with a UPC-A
barcode (template `box_label`). The UPC is a GTIN-12 issued against our GS1 US
company prefix.

### Where the UPC lives

**Shopify's variant `barcode` field is the source of truth.** There is
deliberately no UPC column in Postgres — Shopify already holds the per-variant
row plus the brand, weight and dimension data that GS1 Data Hub wants, so
splitting UPCs across two systems would just create drift.

- Read one: `shopify_client.get_audio_variant_by_sku(sku)` → `["barcode"]`
- Read all: `shopify_client.get_all_product_skus()` → `[sku]["barcode"]`
- Write one: `shopify_client.set_barcode_for_sku(sku, upc)`

Note `get_product_by_sku()` queries the Sundial **Wire** store — it will not
find audio cable SKUs. Use `get_audio_variant_by_sku()` for audio.

### Loading UPCs from GS1

```bash
# Dry run — validates check digits, duplicates, and Shopify conflicts
python tools/audio/audio_upc_sync.py upcs.csv

# Apply (prompts for confirmation; refuses to run if the dry run found errors)
python tools/audio/audio_upc_sync.py upcs.csv --fix

# Which retail variants still have no UPC?
python tools/audio/audio_upc_sync.py --coverage
```

The CSV needs a SKU column and a UPC column; a GS1 Data Hub export works
unmodified (`Internal Part Number or SKU` / `GTIN` are both recognized).
The loader never overwrites an existing UPC — a GTIN assignment is permanent.

### Label stock: use 2" x 3", not the 1" cable roll

A UPC-A symbol is 95 modules wide plus a 9-module quiet zone each side, and at
203 DPI the module width can only be a whole number of dots. That makes
magnification jump in large steps:

| Module width | X-dimension | Magnification | Symbol size | Verdict |
|---|---|---|---|---|
| 2 dots | 0.250 mm | 75.8% | 1.11" x 0.77" | GS1's thermal-print floor is 75% — legal, but zero margin for head wear |
| 3 dots | 0.375 mm | 113.7% | 1.67" x 1.02" | Comfortably in spec — **needs 2" stock** |

`box_label` picks 3 dots when the stock can hold it and falls back to 2 dots on
short stock, logging a warning. On stock too short for both the barcode and the
branding (1" and 1.5" both qualify) it degrades to a barcode-only sticker
rather than printing text over the bars.

The barcode is anchored a fixed distance from the bottom edge so its position
doesn't shift between SKUs — a barcode that moves is a barcode that gets
mis-scanned. Text flows from the top into whatever room is left.

Because the TE210 has one media path, printing box labels means swapping the
roll and recalibrating, so batch them.

### Previewing and printing

```bash
# Geometry report + TSPL, no hardware, no printing
python tools/printer/print_box_label.py SC-20GL --preview

# Preview before UPCs are loaded into Shopify
python tools/printer/print_box_label.py --upc 036000291452 \
    --title "Studio Classic" --subtitle "20 ft - Goldline" --preview

# Check what a different stock size would yield
python tools/printer/print_box_label.py SC-20GL --height-mm 25.4 --preview

# Print 12 on the real printer
python tools/printer/print_box_label.py SC-20GL --count 12
```

`--preview` prints the magnification, quiet zones, and an overlap check, so
verify a new stock size there before committing a roll to it.

### Check digits

`greenlight/gtin.py` holds the GTIN-12 arithmetic. TSPL's `UPCA` type takes
**11 digits and computes the check digit itself**, so we store and validate all
12 and hand the printer the first 11 — making the printer's arithmetic an
independent cross-check on ours. `box_label` refuses to render an invalid
GTIN-12 rather than printing something unscannable.

`gtin.looks_like_gtin12()` exists for scan loops: cable serial numbers are
purely numeric too (see `db.validate_serial_number`), so a scanned 12-digit UPC
would otherwise be zero-padded into a bogus serial. Scan handlers that accept
serials should reject UPCs with it first.

## Retail Shelf Labels (box side)

The shelf label (template `shelf_label`) is the counterpart to the box label.
A boxed cable carries three stickers:

| Face  | Sticker | Template |
|---|---|---|
| Front | Pattern (Goldline, Silverline, ...) | pre-printed, not Greenlight |
| Back  | UPC-A + retail description, 2" x 3" | `box_label` |
| Side  | Length, connector, what cable it is, 1" x 3" | `shelf_label` |

The front and back are both invisible once boxes are racked spine-out, so the
side label is the one a browsing customer actually reads. It leads with the two
things they are choosing between — **length** and **connector** — in the
largest built-in fonts the TE210 has, then names the cable underneath:

```
+---------------------------------------------------------------+
|                                                               |
|  Sundial Audio Studio Series                                  |   font "3"
|  -----------------------------------------------------------  |
|  Goldline                                                     |   font "3"
|                                                               |
|  20' Instrument Cable                                         |   font "4"
|                                                               |
|  TS-TS - Canare GS-6                                          |   font "2"
|                                             SC-20GL           |   font "2"
+---------------------------------------------------------------+
```

Reading order is layout order: who made it, which one, what it is, how it
terminates, then the SKU in the bottom corner.

**Six rows in 203 dots, with roughly even 8–16 dot gaps** which the bitmap
fonts' own leading widens a little further. The pattern row deliberately does
*not* sit tight against the spec row: grouping them that way made the pattern
read as a label on the length rather than as its own line.

**There is deliberately no braid description.** `Goldline` says the same thing
in one word, and at up to three rows the full copy (`Black rayon braid with
gold tracer`) was the single biggest thing on the label. An eight-row version
left 4 dots between rows and read as a wall of text; dropping it buys 60 dots
of breathing room. `describe_variant()` still returns that copy as `detail`
for callers with room for it — the storefront listing, the GS1 back label —
this template just doesn't print it.

**The connector row is the product-facing designation**, not the engineering
shorthand. A right-angle cable reads `TS-TS Right Angle`, because both of its
ends really are TS with one of them angled — inventing a second pair name
(`RA-TS`) is an internal convenience, and a test asserts it never reaches a
label. Nothing on the label restates a default either: no row says a mic cable
is XLR male-to-female, because it always is.

**The core cable rides on that row** rather than having one of its own, since
`Canare GS-6` is the part of the spec a customer recognizes and the row has
width going spare.

**The SKU gets its own row** at the bottom right, 28 dots in from the edge
against the 16-dot left gutter. It could share the connector's row and for
most variants would sit clear — but the longest connector line
(`TS-TS Right Angle - Canare GS-6`, 31 characters) ends only 5 dots short of
where the SKU starts, and a third of the catalog is right-angle. Not worth the
margin.

### What each change costs

Every row is spoken for, so reaching for a bigger font means taking space from
something else. The history, because each step here was paid for:

| Change | Cost | Paid for by |
|---|---|---|
| Spec row font `"4"` → `"5"` | +16 dots | dropping the word "Cable" (18-char row) and the SKU's own row |
| Spec row back to font `"4"` | −16 dots | "Cable" restored, SKU got its row back |
| Description font `"1"` → `"2"` | +16 dots, capacity 144 → 96 chars | the core cable moving to the connector row |
| Description given a 3rd row | +24 dots | sharing the SKU's row |
| Description dropped entirely | **−60 dots** | became the gaps between the six remaining rows |

### Font metrics: measure, don't trust the manual

`SHELF_FONT_ADVANCE` is the horizontal advance per character, and it is **not**
the font cell width the TSPL manual lists. The printer adds about 2 dots of
inter-character spacing, so a row holds ~17% fewer characters than the cell
width suggests:

| Font | Manual cell | Actual advance | Chars in 577 dots |
|---|---|---|---|
| `"1"` | 8 × 12 | 10 | 57 |
| `"2"` | 12 × 20 | 14 | 41 |
| `"3"` | 16 × 24 | 18 | 32 |
| `"4"` | 24 × 32 | 26 | 22 |
| `"5"` | 32 × 48 | 34 | 16 |

This was calibrated off a printed label: a 45-character font `"2"` row ran
about 3 characters past the edge, which puts the advance at 14 rather than 12.
The 12 came from the manual via `tools/printer/print_font_samples.py`, and
believing it is what let an over-wide row reach real stock — the geometry
tests were computing with the same wrong number, so they passed. **Re-measure
before trusting these on a different printer or DPI.** `tests/test_shelf_label.py`
mirrors the table and asserts it matches the template's, so the two can't
drift apart again.

The spec row has the least headroom: 22 characters against a longest actual
value of 20.

**The connector row is the product-facing designation**, not the engineering
shorthand. A right-angle cable reads `TS-TS Right Angle`, because both of its
ends really are TS with one of them angled — inventing a second pair name
(`RA-TS`) is an internal convenience, and a test asserts it never reaches a
label. Nothing on the label restates a default either: no row says a mic cable
is XLR male-to-female, because it always is.

**The core cable rides on that row** rather than leading the description. At
font `"2"` the description's two rows hold 96 characters, and
`Canare L-4E6S core - ` plus the longest pattern description is 110. The
pattern description alone is 89, so the braid copy gets its own rows and
`Canare GS-6` — the part of the spec a customer recognizes — sits next to the
connector instead.

**The SKU is bottom-right**, with a wider margin than the left gutter
(`SHELF_X_SKU_PAD`): it sits alone in the corner, where a tight margin reads
as a crop rather than as a choice.

### Where the text comes from

`cable_config.describe_variant(sku)` resolves a variant SKU to exactly the keys
the template wants, straight out of `catalog/`:

```python
describe_variant("SC-20GL")
# {'brand_line':      'Sundial Audio Studio Series',   # 1. font "3"
#  'pattern':         'Goldline',                      # 2. font "3"
#  'spec_line':       "20' Instrument Cable",          # 3. font "4"
#  'connector_line':  'TS-TS - Canare GS-6',           # 4. font "2"
#  'sku':             'SC-20GL',                       # 5. font "2"
#  'detail': 'Black rayon braid with gold tracer',  # NOT printed on the label
#  'cable_type': 'Instrument',       # the atoms the rows are built from
#  'connector_label': 'TS-TS',
#  'length': '20',
#  'connector': 'TS-TS',             # raw shorthand; 'RA-TS' on right-angle
#  ...}
```

Pure YAML lookup — no Postgres and no Shopify — so shelf labels print with the
DB tunnel down, the same constraint `gtin.py` carries for box labels.

### The brand line: `retail_family`, not `product_line`

`cable_lines.yaml` carries a **`retail_family`** per series (`Studio`,
`Touring`) and the brand line is `Sundial Audio {retail_family} Series`. It is
deliberately coarser than `product_line`: the boxes are generic Studio and
Touring, the pattern has its own row, and the spec row already says Instrument
or Microphone — so `Sundial Audio Studio Vocal Classic Series` would be both
redundant and 41 characters in a 36-character row.

`retail_family` is optional in the schema (the brand line falls back to
`product_line` without it), but `test_every_series_declares_a_retail_family`
requires one on every series. It is mirrored in
`shopify_app/app/cable-config-schemas.js` because the per-series shape there
is `additionalProperties: false` and would otherwise reject the YAML.

### Cable types and connector names

Both live in `cable_config.RETAIL_CABLE_TYPES`, keyed by connector display
string:

```python
'TS-TS':   {'type': 'Instrument', 'label': 'TS-TS'},
'RA-TS':   {'type': 'Instrument', 'label': 'TS-TS Right Angle'},
'XLR-XLR': {'type': 'Microphone', 'label': 'XLR-XLR'},
```

**Adding a series with a new connector display means adding an entry there**,
or the spec row loses the word that says what the cable is and the connector
row prints blank. Three rules, each with a test behind it:

- **`type` fits the spec row.** That row holds 24 characters at font `"4"`;
  `25' ` and ` Cable` spend 10, so a type word has 14. Both catalog types
  are 10.
- **`label` fits its row** alongside the core cable (font `"2"`, 48
  characters; the longest today is `TS-TS Right Angle - Canare L-4E6S` at 33).
- **No `"` anywhere.** TSPL can't escape it and the template swaps it for
  `'`, which would turn `1/4"` into `1/4'` — feet. Feet use the prime (`20'`),
  which is safe; inch marks simply don't appear on these labels.

### Overriding a row

```bash
python tools/printer/print_shelf_label.py SC-20GL --pattern "Phish 2026"
```

`--brand`, `--pattern`, `--spec` and `--connector` each replace one row, and
`--no-sku` drops the corner SKU for a purely customer-facing label. There is
no `--detail`: the label has no description row to override.

### (Historical) why body text is filled, not balanced

The description is gone, but the reasoning is worth keeping, because the same
trap waits for any future multi-row text. `_wrap_to_rows()` filled each row
before starting the next, across up to three rows of 41 / 41 / 30 characters
— the third shorter because it shared the SKU's baseline:

| Pattern | Description | Rows |
|---|---|---|
| Pearl White | 23 chars | 1 |
| Goldline | 34 chars | 1 |
| Houndstooth Putty | 48 chars | 2 — filled to 41, then `tracer` |
| Neon Jungle | 89 chars | 3, the last on the SKU's row |

An earlier version deliberately *balanced* the rows instead, on a misreading
of "break the description to the next line" as "always use two rows". It broke
`Black rayon braid with gold tracer` across two rows when it fits comfortably
on one, and broke Houndstooth Putty at its midpoint rather than filling the
first row. **Greedy fill is what's wanted for body text; balancing is not.**

### Printing

```bash
# Resolved content + TSPL, no hardware
python tools/printer/print_shelf_label.py SC-20GL --preview

# Print 12 for a shelf facing
python tools/printer/print_shelf_label.py SC-20GL --count 12

# Override any row (e.g. a seasonal tagline instead of the materials)
python tools/printer/print_shelf_label.py SC-20GL \
    --detail "Hand-braided in Ohio" --preview

# Drop the corner SKU for a pure customer-facing label
python tools/printer/print_shelf_label.py SC-20GL --no-sku --preview
```

### Fonts and fixed positions

Element positions are **fixed constants** (`TSCLabelPrinter.SHELF_*`), not
flowed from the content. These labels sit side by side on a retail shelf, so a
row has to land in the same spot on every box or a rank of them reads as
ragged.

Every row is **clipped to its width, not wrapped** — the vertical budget is
spoken for, so a row that outgrew itself would have to push another off the
label. Only the description wraps, because it has two rows of its own.

That makes the catalog sweep the real guard. `tests/test_shelf_label.py`
renders **every** catalog variant and asserts that no element leaves the label,
no two overlap, no byte is non-ASCII, each row fits without clipping, and the
description neither truncates nor comes out lopsided. The TE210 does all of
those wrong silently, and you would only find out after a roll of stock. When a
new catalog name doesn't fit, the test says so and names it — shorten the name
rather than growing the label.

## Printing a batch

### Printing a wholesale order

In Greenlight: **`f` from the scan hub**, pick a Wholesale order, and scan
its cables. Each cable's **registration label prints as it is scanned** (1"
roll), because the code belongs to that one cable and printing it with the
cable in hand is what keeps the two together; rescanning reprints it. Then
**`l`** opens the box labels: side + Prop 65 together on the 1" roll, UPC on
the 2". Toggle which labels you want; the toggles re-cost the plan live, so
you can see that dropping the UPC label takes a mixed run from one roll swap
to none before committing to it.

Website orders get no box labels — they're scanned against the order and
that's all. This used to be its own `o` hub key, which left two lists of
outstanding work that disagreed; see CLAUDE.md § Order fulfillment.

Or from the command line:

```bash
python tools/printer/print_order_labels.py --list          # recent drafts
python tools/printer/print_order_labels.py D14 --preview    # the plan
python tools/printer/print_order_labels.py D14 --labels side
python tools/printer/print_order_labels.py D14
```

**Wholesale orders are Shopify DRAFT orders.** `shopify_app/app/b2b.server.js`
creates a draft and emails an invoice, and never completes it — the buyer
paying is what turns it into an Order. So an unpaid wholesale order is a
draft for its whole working life, including when its labels get printed, and
`get_customer_orders()` cannot see it: drafts are a separate GraphQL root.
Hence `shopify_client.get_draft_orders()` and `get_draft_order_by_name()`.

**Which labels to print is asked per job**, not fixed, because it varies —
not every retailer wants the UPC label, and Prop 65 placement is unsettled.
Deselecting one also changes what the run costs:

```
#D14, 24 cables over 6 SKUs
  all three            72 labels, 13 jobs, 1 roll swap
  side + prop65        48 labels,  7 jobs, 0 roll swaps
```

`greenlight/label_batch.py` does the planning, with no printer, DB or
Shopify, so the awkward parts are testable. Two things shape its output:

- **Grain.** The retail labels are per *variant*: four identical cables are
  one job with `PRINT 4`, not four jobs. That is why a 24-cable order is 12
  connections. `registration_label` is deliberately **not** planned here —
  it carries a unique code per physical cable, keyed to serials that live in
  Postgres rather than in the order, so it belongs with the cable batch in
  `screens/wholesale.py` where the serials already are.
- **Stock.** Jobs are grouped by stock and printed one group at a time, so a
  mixed run costs one roll swap rather than one per label.

**Lines that cannot be printed warn rather than vanish.** A wholesale order
that quietly prints 20 labels instead of 24 is worse than one that refuses:

| Line | Outcome |
|---|---|
| MISC / LTD build (e.g. `TC-MISC-51`) | skipped, warned — no retail UPC, and no catalog length or connector, so most of a side label would be blank |
| SKU the catalog doesn't know | skipped, warned |
| Catalog SKU with no UPC in Shopify | UPC label skipped, **side label still prints** |

Those cases are real: order `#D4` in the store is five MISC one-offs.

### Copies are the printer's job

`PrintJob(quantity=N)` prints N labels from **one** connection: TSPL's
`PRINT m,n` takes m sets of n copies, so the printer does the repeat.

This did not work until 2026-10-05. Eight of the nine templates hardcoded
`PRINT 1` while `print_labels()` logged *"Successfully printed
{print_job.quantity} label(s)"* — so a job for 12 produced one and reported
twelve, and every caller that wanted N had to loop, opening N sockets. For a
wholesale order of 50 cables that is 150 round trips instead of a handful.

The count reaches the template through `data['quantity']`, which
`print_labels()` fills in from `PrintJob.quantity` with `setdefault` — so a
caller that puts it in `data` directly still wins (that is how
`print_prop65.py` has always passed it). It is floored at 1, and junk values
fall back to 1 rather than raising inside a template.

### Which stock a template needs

`LABEL_STOCK` maps each template to the stock it is designed for:

```python
from greenlight.hardware.tsc_label_printer import stock_for_template
stock_for_template("box_label")    # (76.2, 50.8) -- 2" x 3"
stock_for_template("shelf_label")  # (76.2, 25.4) -- 1" x 3"
```

`box_label` is the only one wanting the tall stock, because a UPC-A renders
only at whole-dot module widths and 1" forces it to the 75% thermal floor.

This is data rather than an `if template == "box_label"` branch because two
things need it. **Grouping a run by stock** keeps a mixed job set to one roll
swap instead of one per label — the TE210 has a single media path:

```python
groups = {}
for template in run:
    groups.setdefault(stock_for_template(template), []).append(template)
# print each group, swap the roll between them
```

And **routing to a second printer** by what it has loaded, once there is one
(see the roadmap note in `UPC_ROLLOUT_STATUS.md`).

### One dispatch table

`TSCLabelPrinter.TEMPLATES` maps a template name to its generator method, and
both the real printer and the mock use it. They were two parallel `if/elif`
chains before, and had already drifted: the mock was silently missing
`box_label` and `shelf_label`. `LABEL_STOCK` and `TEMPLATES` must have
identical keys, which `tests/test_label_batching.py` asserts — so a new
template cannot be added without a stock declaration.

### Label grain, for a wholesale order

The labels do not all repeat the same way, which is what makes a batch run
two passes rather than one loop:

| Label | Grain | For 10 x SC-20GL |
|---|---|---|
| `box_label`, `shelf_label` | per **variant** | 10 identical — one job, `PRINT 10` |
| `prop65_label` | per **order** | one job for the order's whole box count |
| `registration_label` | per **cable** | 10 unique codes — 10 jobs |

**Prop 65 goes on the 1" roll**, as its own sticker on the box back. It was
considered for the 2"x3" UPC label and does not fit at a compliant type size:
`www.P65Warnings.ca.gov` is 22 unbreakable characters, which needs 23 per line
and so only font `"1"` — and that is ~4.3 pt, under the 6 pt floor. Its own
label has no competing text, so the "no smaller than other consumer
information" clause has nothing to bind against either.

Its text says nothing about the cable, so it is **one job for the order**, not
one per SKU — six variants would otherwise mean six jobs printing identical
labels. It counts every box including MISC and LTD lines whose retail labels
get skipped: shipping without the warning is a compliance problem, shipping
without a side label is untidy.

`greenlight/screens/wholesale.py` `_generate_and_print()` is the existing
precedent for the per-cable half.

## Usage in Greenlight

### During Cable Registration

After registering a cable, the system will automatically offer to print a label:

1. Register cable by scanning barcode
2. System saves cable to database
3. **Prompt appears**: "Print label now?"
   - Press `y` to print the label
   - Press `n` or `Enter` to skip
4. If printing, system will:
   - Generate TSPL commands based on cable data
   - Send to printer
   - Show success/failure message
5. Continue scanning next cable

### Workflow Integration

Label printing is integrated into these workflows:
- **Cable Intake** (primary workflow)
  - After each successful cable registration
  - Optional - can skip if not needed

## Label Data

Labels include the following information:
- **Brand**: SUNDIAL AUDIO (static)
- **Series**: Cable series (e.g., "Studio Series", "Tour Series")
- **Length**: Cable length in feet (e.g., "20'")
- **Color/Pattern**: Color or pattern name (e.g., "Goldline", "Black")
- **Connector**: Connector type (e.g., "Straight Connectors", "TS to TRS")
- **SKU**: Product SKU code (e.g., "SC-20GL")
- **Description**: For MISC cables only - custom description

## Troubleshooting

### Printer Not Responding

**Symptoms**: "TSC printer not responding" message at startup

**Solutions**:
1. Check printer power
2. Check network cable connection
3. Verify IP address: `ping 192.168.0.52`
4. Check printer network settings via front panel
5. Verify printer is on same network/VLAN
6. Try accessing printer web interface: `http://192.168.0.52`

### Labels Not Printing

**Symptoms**: Print job sent but no label comes out

**Solutions**:
1. Check paper/label stock is loaded
2. Verify label size matches printer settings
3. Check for paper jams
4. Verify thermal transfer ribbon is installed (if using thermal transfer mode)
5. Check printer status lights for errors

### Label Quality Issues

**Symptoms**: Faint or poor quality prints

**Solutions**:
1. Adjust print density (currently set to 10, range 0-15)
2. Adjust print speed (currently set to 3, range 2-4)
3. Check ribbon and label stock compatibility
4. Clean print head

### Wrong Label Size

**Symptoms**: Content doesn't fit or is misaligned

**Solutions**:
1. Verify label stock is 1" x 3" (25.4mm x 76.2mm)
2. Check printer media settings
3. Verify `TSC_LABEL_WIDTH_MM` and `TSC_LABEL_HEIGHT_MM` in config
4. Run printer calibration routine

## Advanced Configuration

### Adjusting Print Quality

Edit `greenlight/hardware/tsc_label_printer.py`:

```python
# Set print density (0-15, where 8 is medium, 10 is default)
tspl_commands.append("DENSITY 10")

# Set print speed (2-4 inches/sec, where 3 is default)
tspl_commands.append("SPEED 3")
```

### Customizing Label Layout

The label layout is generated in `_generate_cable_label_tspl()` method of `TSCLabelPrinter` class.

Key positioning variables:
```python
# Y positions (from top, in dots at 203 DPI)
y_brand = 10      # SUNDIAL AUDIO at top
y_series = 60     # Series name
y_length = 95     # Length and color/pattern
y_connector = 130 # Connector type and SKU

# X positions (from left, in dots)
x_left = 10
x_right = 580     # Right side for SKU
```

Font sizes:
- `"3"` = Large (brand, series)
- `"2"` = Medium (length, SKU)
- `"1"` = Small (connector details)

## TSPL Command Reference

The printer uses TSPL (TSC Printer Language) commands. Key commands:

```
SIZE 76.2 mm, 25.4 mm      # Set label size
GAP 2 mm, 0 mm             # Set gap between labels
DIRECTION 1,0              # Print direction
DENSITY 10                 # Print darkness (0-15)
SPEED 3                    # Print speed (2-4)
CLS                        # Clear image buffer
TEXT x,y,"font",rotation,x_mult,y_mult,"text"  # Print text
BAR x,y,width,height       # Draw rectangle/line
PRINT qty,copies           # Print label
```

## Reference Files

- **Sample Label PDF**: `SC-20GL.pdf` - Reference design for label layout
- **Printer Module**: `greenlight/hardware/tsc_label_printer.py`
- **Text Label Script**: `tools/printer/print_label.py`
- **Prop 65 Label Script**: `tools/printer/print_prop65.py`
- **Box Label Script**: `tools/printer/print_box_label.py`
- **Shelf Label Script**: `tools/printer/print_shelf_label.py`
- **Configuration**: `greenlight/config.py`

## Support

For printer-specific issues:
- TSC TE210 Manual: [TSC Support Website](https://www.tscprinters.com/)
- TSPL Programming Manual available from TSC

For Greenlight integration issues:
- Check logs in `/tmp/greenlight_debug.log`
- Review hardware manager status in application
