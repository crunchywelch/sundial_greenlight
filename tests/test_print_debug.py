#!/usr/bin/env python3
"""
Debug script to see exactly what TSPL commands are being sent to the printer
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob
from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM

print("=" * 70)
print("TSPL Command Debug")
print("=" * 70)
print()

# Create printer
printer = TSCLabelPrinter(
    ip_address=TSC_PRINTER_IP,
    port=TSC_PRINTER_PORT,
    label_width_mm=TSC_LABEL_WIDTH_MM,
    label_height_mm=TSC_LABEL_HEIGHT_MM
)

# Sample label data (SC-20GL)
label_data = {
    'series': 'Studio Series',
    'length': '20',
    'color_pattern': 'Goldline',
    'connector_type': 'Straight',
    'sku': 'SC-20GL'
}

print("Label Data:")
for key, value in label_data.items():
    print(f"  {key}: {value}")
print()

# Generate TSPL commands
tspl = printer._generate_cable_label_tspl(label_data)

print("=" * 70)
print("TSPL Commands Being Sent:")
print("=" * 70)
print(tspl)
print("=" * 70)
print()

# Show byte representation
print("Byte representation (first 200 bytes):")
print(repr(tspl.encode('utf-8')[:200]))
print()

# Ask if user wants to send to printer
response = input("Send these commands to printer? (y/n): ").strip().lower()

if response == 'y':
    print()
    print("Initializing printer...")
    if printer.initialize():
        print("✅ Printer initialized")

        print("Sending commands...")
        success = printer._send_tspl_commands(tspl)

        if success:
            print("✅ Commands sent successfully")
            print()
            print("Check the printer:")
            print("  - Did a label print?")
            print("  - Are there any error lights?")
            print("  - Check printer display for errors")
        else:
            print("❌ Failed to send commands")
    else:
        print("❌ Failed to initialize printer")
else:
    print("Cancelled")

print()
print("If no label printed, possible issues:")
print("  1. Printer is in pause mode")
print("  2. Label stock not loaded correctly")
print("  3. Printer needs to be calibrated")
print("  4. TSPL syntax error")
print()
