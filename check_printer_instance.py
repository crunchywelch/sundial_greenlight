#!/usr/bin/env python3
"""
Check if hardware_manager returns the correct printer instance
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.config import USE_REAL_PRINTERS, TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM
from greenlight.hardware.interfaces import hardware_manager, PrintJob

print("=" * 70)
print("Checking Printer Instance")
print("=" * 70)
print()

# Initialize like the app does
print("1. Initializing printer like the app...")
if USE_REAL_PRINTERS:
    from greenlight.hardware.tsc_label_printer import TSCLabelPrinter

    label_printer = TSCLabelPrinter(
        ip_address=TSC_PRINTER_IP,
        port=TSC_PRINTER_PORT,
        label_width_mm=TSC_LABEL_WIDTH_MM,
        label_height_mm=TSC_LABEL_HEIGHT_MM
    )
    label_printer.initialize()
    hardware_manager.set_hardware(label_printer=label_printer)
    print(f"   ✅ Set printer in hardware_manager: {label_printer}")
else:
    from greenlight.hardware.tsc_label_printer import MockTSCLabelPrinter
    mock_printer = MockTSCLabelPrinter(ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT)
    mock_printer.initialize()
    hardware_manager.set_hardware(label_printer=mock_printer)
    print(f"   ✅ Set mock printer in hardware_manager")

print()

# Get it back like the app does
print("2. Getting printer from hardware_manager...")
retrieved_printer = hardware_manager.get_label_printer()
print(f"   Retrieved: {retrieved_printer}")
print(f"   Same instance? {retrieved_printer is label_printer if USE_REAL_PRINTERS else retrieved_printer is mock_printer}")
print()

# Check if it's connected
print("3. Checking printer status...")
if retrieved_printer:
    print(f"   Connected: {retrieved_printer.connected if hasattr(retrieved_printer, 'connected') else 'N/A'}")
    print(f"   Ready: {retrieved_printer.is_ready()}")
    print()

# Try printing
print("4. Attempting to print...")
test_data = {
    'series': 'Studio Series',
    'length': '20',
    'color_pattern': 'Goldline',
    'connector_type': 'Straight',
    'sku': 'SC-20GL'
}

print_job = PrintJob(
    template="cable_label",
    data=test_data,
    quantity=1
)

print("   Sending print job...")
success = retrieved_printer.print_labels(print_job)
print(f"   Result: {success}")
print()

if success:
    print("✅ Print job sent successfully via hardware_manager!")
    print("   If label didn't print, check:")
    print("   1. Printer display for errors")
    print("   2. Paper loaded correctly")
    print("   3. Printer in pause mode")
else:
    print("❌ Print job failed")
