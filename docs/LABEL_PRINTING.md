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
- **Configuration**: `greenlight/config.py`

## Support

For printer-specific issues:
- TSC TE210 Manual: [TSC Support Website](https://www.tscprinters.com/)
- TSPL Programming Manual available from TSC

For Greenlight integration issues:
- Check logs in `/tmp/greenlight_debug.log`
- Review hardware manager status in application
