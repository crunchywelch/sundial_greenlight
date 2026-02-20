#!/usr/bin/env python3
"""
Compare what the app sends vs what test_label_printer.py sends
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter
from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM

print("=" * 70)
print("Comparing App vs Test Script Data")
print("=" * 70)
print()

# Create printer
printer = TSCLabelPrinter(
    ip_address=TSC_PRINTER_IP,
    port=TSC_PRINTER_PORT,
    label_width_mm=TSC_LABEL_WIDTH_MM,
    label_height_mm=TSC_LABEL_HEIGHT_MM
)

# Test script data (string length)
test_data = {
    'series': 'Studio Series',
    'length': '20',  # STRING
    'color_pattern': 'Goldline',
    'connector_type': 'Straight',
    'sku': 'SC-20GL'
}

# App data (float length like from database)
app_data = {
    'series': 'Studio Series',
    'length': 20.0,  # FLOAT (what database returns)
    'color_pattern': 'Goldline',
    'connector_type': 'Straight',
    'sku': 'SC-20GL'
}

print("TEST SCRIPT DATA:")
print(f"  length type: {type(test_data['length'])}")
print(f"  length value: {test_data['length']}")
print()

print("APP DATA (from database):")
print(f"  length type: {type(app_data['length'])}")
print(f"  length value: {app_data['length']}")
print()

# Generate TSPL for both
print("=" * 70)
print("TSPL from TEST DATA:")
print("=" * 70)
test_tspl = printer._generate_cable_label_tspl(test_data)
print(test_tspl)
print()

print("=" * 70)
print("TSPL from APP DATA:")
print("=" * 70)
app_tspl = printer._generate_cable_label_tspl(app_data)
print(app_tspl)
print()

# Compare
if test_tspl == app_tspl:
    print("✅ IDENTICAL - Both generate the same TSPL commands")
else:
    print("❌ DIFFERENT - TSPL commands differ")
    print()
    print("Looking for differences...")
    test_lines = test_tspl.split('\n')
    app_lines = app_tspl.split('\n')

    for i, (test_line, app_line) in enumerate(zip(test_lines, app_lines)):
        if test_line != app_line:
            print(f"  Line {i+1} differs:")
            print(f"    Test: {test_line}")
            print(f"    App:  {app_line}")
