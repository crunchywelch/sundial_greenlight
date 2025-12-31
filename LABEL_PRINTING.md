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
python test_label_printer.py --mock
```

This will simulate label printing without connecting to actual hardware.

### Test with Real Printer

1. Ensure printer is powered on and connected to network
2. Verify network connectivity: `ping 192.168.0.52`
3. Run the test script:

```bash
python test_label_printer.py
```

The script will:
- Connect to the printer
- Generate sample labels for different cable types
- Ask for confirmation before printing each label
- Display status and results

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
- **Register Cables** (primary workflow)
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
- **Test Script**: `test_label_printer.py`
- **Configuration**: `greenlight/config.py`

## Support

For printer-specific issues:
- TSC TE210 Manual: [TSC Support Website](https://www.tscprinters.com/)
- TSPL Programming Manual available from TSC

For Greenlight integration issues:
- Check logs in `/tmp/greenlight_debug.log`
- Review hardware manager status in application
