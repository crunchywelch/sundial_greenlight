#!/usr/bin/env bash
# printer_setup.sh: Initialize a new TSC TE210 label printer for use with Greenlight
#
# New TE210 printers ship in ZPL mode. This script switches them to TSPL mode
# and sends calibration commands for 1" x 3" labels.
#
# Usage: ./printer_setup.sh <printer-ip>
#
# Steps performed:
#   1. Send ~!T (ZPL command to switch to TSPL mode)
#   2. Wait for user to power cycle the printer
#   3. Send TSPL calibration commands
#   4. Print a test label to verify

set -euo pipefail

PRINTER_PORT=9100

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <printer-ip>"
  echo ""
  echo "Example: $0 192.168.0.52"
  exit 1
fi

PRINTER_IP="$1"

send_to_printer() {
  printf '%s' "$1" | nc -q 2 "$PRINTER_IP" "$PRINTER_PORT"
}

echo "========================================"
echo "  TSC TE210 Printer Setup"
echo "========================================"
echo ""
echo "Printer: $PRINTER_IP:$PRINTER_PORT"
echo ""

# Step 1: Check connectivity
echo "[1/4] Checking connectivity..."
if ! nc -z -w 3 "$PRINTER_IP" "$PRINTER_PORT" 2>/dev/null; then
  echo "  ERROR: Cannot reach $PRINTER_IP:$PRINTER_PORT"
  echo "  Check that the printer is on and connected to the network."
  exit 1
fi
echo "  OK - printer is reachable"
echo ""

# Step 2: Switch from ZPL to TSPL mode
echo "[2/4] Sending language switch command (~!T)..."
echo "  This switches the printer from ZPL to TSPL mode."
echo "  (If already in TSPL mode, this is harmless.)"
send_to_printer $'~!T\r\n'
echo "  Sent."
echo ""

echo "  >>> POWER CYCLE THE PRINTER NOW <<<"
echo ""
read -rp "  Press Enter after the printer has restarted..."
echo ""

# Step 3: Send calibration commands
echo "[3/4] Sending TSPL calibration commands..."
send_to_printer $'SIZE 76.2 mm, 25.4 mm\r\nGAP 2 mm, 2 mm\r\nDIRECTION 1,0\r\nREFERENCE 0,0\r\nSET TEAR ON\r\nSET PEEL OFF\r\nDENSITY 10\r\nSPEED 3\r\nCLS\r\n'
echo "  Calibration sent."
echo ""

# Step 4: Print test label
echo "[4/4] Printing test label..."
send_to_printer $'SIZE 76.2 mm, 25.4 mm\r\nGAP 2 mm, 2 mm\r\nDIRECTION 1,0\r\nCLS\r\nTEXT 20,12,"3",0,1,1,"SUNDIAL AUDIO"\r\nBAR 20,40,300,2\r\nTEXT 20,60,"2",0,1,1,"Printer Setup OK"\r\nTEXT 20,100,"1",0,1,1,"TSPL mode confirmed"\r\nPRINT 1\r\n'
echo "  Test label sent."
echo ""

echo "========================================"
echo "  Setup complete!"
echo "========================================"
echo ""
echo "If the test label printed correctly (not hex codes),"
echo "the printer is ready to use with Greenlight."
echo ""
echo "If it printed hex codes instead, try running this"
echo "script again — the power cycle may not have completed."
