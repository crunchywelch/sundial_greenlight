#!/usr/bin/env python3
"""
Test startup sequence to identify where hang occurs
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("Testing Greenlight Startup Sequence")
print("=" * 60)
print()

print("1. Testing imports...")
from greenlight.config import USE_REAL_PRINTERS, TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM
print(f"   ✅ Config loaded - USE_REAL_PRINTERS={USE_REAL_PRINTERS}")

print("\n2. Testing hardware manager import...")
from greenlight.hardware.interfaces import hardware_manager
print("   ✅ Hardware manager imported")

print("\n3. Testing printer class import...")
if USE_REAL_PRINTERS:
    from greenlight.hardware.tsc_label_printer import TSCLabelPrinter
    print("   ✅ TSCLabelPrinter imported")
else:
    from greenlight.hardware.tsc_label_printer import MockTSCLabelPrinter
    print("   ✅ MockTSCLabelPrinter imported")

print("\n4. Creating printer instance...")
if USE_REAL_PRINTERS:
    label_printer = TSCLabelPrinter(
        ip_address=TSC_PRINTER_IP,
        port=TSC_PRINTER_PORT,
        label_width_mm=TSC_LABEL_WIDTH_MM,
        label_height_mm=TSC_LABEL_HEIGHT_MM
    )
    print(f"   ✅ Printer instance created for {TSC_PRINTER_IP}")
else:
    label_printer = MockTSCLabelPrinter(ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT)
    print("   ✅ Mock printer instance created")

print("\n5. Initializing printer...")
if label_printer.initialize():
    print("   ✅ Printer initialized successfully")
else:
    print("   ⚠️  Printer initialization failed")

print("\n6. Setting hardware in manager...")
hardware_manager.set_hardware(label_printer=label_printer)
print("   ✅ Hardware manager configured")

print("\n7. Getting printer from manager...")
test_printer = hardware_manager.get_label_printer()
print(f"   ✅ Got printer: {test_printer}")

print("\n8. Checking if printer is ready...")
if test_printer:
    is_ready = test_printer.is_ready()
    print(f"   ✅ Printer ready check: {is_ready}")

print("\n9. Testing UI import...")
from greenlight.ui import UIBase
print("   ✅ UI imported")

print("\n10. Testing screen manager import...")
from greenlight.screen_manager import ScreenManager
print("   ✅ Screen manager imported")

print("\n11. Testing screens import...")
from greenlight.screens import SplashScreen
print("   ✅ Screens imported")

print()
print("=" * 60)
print("✅ All startup steps completed successfully!")
print("=" * 60)
print()
print("If the real app hangs, the issue is in:")
print("  - Screen rendering logic")
print("  - User input handling")
print("  - Screen transition code")
