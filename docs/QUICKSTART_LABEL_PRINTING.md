# Quick Start: TSC TE210 Label Printing

## Overview

Your Greenlight system now supports automatic label printing with the TSC TE210 thermal transfer printer. This guide will get you up and running quickly.

## Initial Setup (One Time)

### 1. Configure Environment

Add to your `.env` file:

```bash
# Enable the real printer
GREENLIGHT_USE_REAL_PRINTERS=true

# Printer is already configured for IP 192.168.0.52
# If your printer has a different IP, add:
# GREENLIGHT_TSC_PRINTER_IP=192.168.0.xx
```

### 2. Test Connection

```bash
# Test network connectivity
ping 192.168.0.52

# Test printer with mock mode (no actual printing)
python test_label_printer.py --mock

# Test with real printer (will print 3 sample labels)
python test_label_printer.py

# Test by printing the reference PDF (SC-20GL.pdf)
python test_print_pdf.py
```

## Daily Usage

### Starting Greenlight

When you start the application:

```bash
source dev_env.sh
python -m greenlight.main
```

You'll see:

```
🚀 Starting Greenlight Terminal...
🖨️  Initializing TSC label printer...
✅ TSC printer ready at 192.168.0.52
```

If you see this warning instead:
```
⚠️  TSC printer not responding at 192.168.0.52
   Label printing will be unavailable
```

Check that the printer is powered on and connected to the network.

### Printing Labels During Cable Registration

1. **Select Cable Type**: Choose series → color → length → connector
2. **Scan Cable**: Scan the barcode on the cable
3. **Confirm**: Press Enter to save
4. **Print Prompt**: System asks "Print label now?"
   - Press `y` to print
   - Press `n` or Enter to skip
5. Label prints automatically
6. Apply label to cable
7. Continue scanning next cable

### Workflow Tips

- **Batch printing**: Print labels as you register each cable
- **Skip printing**: Just press Enter if you don't need labels
- **Printer offline**: If printer is offline, registration still works - just skip label printing

## Label Information

Each label includes:
- **SUNDIAL AUDIO** branding
- **Series** (e.g., "Studio Series")
- **Length** (e.g., "20'")
- **Color/Pattern** (e.g., "Goldline")
- **Connector Type** (e.g., "Straight Connectors")
- **SKU** (e.g., "SC-20GL")

For MISC cables, the custom description is also printed.

## Troubleshooting

### Printer Not Found
```
⚠️  TSC printer not responding at 192.168.0.52
```

**Fix**:
1. Check printer power
2. Verify network connection: `ping 192.168.0.52`
3. Check printer front panel for network settings

### Labels Not Printing

**Fix**:
1. Check label stock is loaded (1" x 3" labels)
2. Check thermal transfer ribbon is installed
3. Check printer for error lights/messages
4. Try test print from printer menu

### Label Quality Issues

**Fix**:
1. Adjust print density (see LABEL_PRINTING.md)
2. Check ribbon and label compatibility
3. Clean print head

## Mock Mode (Testing Without Printer)

To test without the real printer:

```bash
# In .env file:
GREENLIGHT_USE_REAL_PRINTERS=false
```

The system will simulate printing and log what would have been printed.

## Next Steps

- See **LABEL_PRINTING.md** for detailed configuration and troubleshooting
- Adjust print quality settings if needed
- Customize label layout for your needs

## Quick Reference

| Action | Command |
|--------|---------|
| Test connection | `ping 192.168.0.52` |
| Test mock printer | `python test_label_printer.py --mock` |
| Test real printer | `python test_label_printer.py` |
| Enable printer | Set `GREENLIGHT_USE_REAL_PRINTERS=true` in .env |
| Disable printer | Set `GREENLIGHT_USE_REAL_PRINTERS=false` in .env |

## Support

- Detailed docs: `LABEL_PRINTING.md`
- Printer manual: TSC TE210 documentation
- Printer web interface: `http://192.168.0.52` (if enabled)
