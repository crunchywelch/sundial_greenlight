#!/usr/bin/env python3
"""
Test script for TSC TE210 label printer

This script tests the label printer by:
1. Connecting to the printer
2. Generating TSPL commands for a sample label
3. Sending the label to the printer

Usage:
    python test_label_printer.py [--mock]

Options:
    --mock    Use mock printer (no actual hardware)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, MockTSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob
from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM


def test_label_printer(use_mock=False):
    """Test the TSC label printer"""

    print("=" * 60)
    print("TSC TE210 Label Printer Test")
    print("=" * 60)
    print()

    # Create printer instance
    if use_mock:
        print("Using MOCK printer (no actual hardware)")
        printer = MockTSCLabelPrinter(
            ip_address=TSC_PRINTER_IP,
            port=TSC_PRINTER_PORT
        )
    else:
        print(f"Using REAL printer at {TSC_PRINTER_IP}:{TSC_PRINTER_PORT}")
        printer = TSCLabelPrinter(
            ip_address=TSC_PRINTER_IP,
            port=TSC_PRINTER_PORT,
            label_width_mm=TSC_LABEL_WIDTH_MM,
            label_height_mm=TSC_LABEL_HEIGHT_MM
        )

    print()

    # Initialize printer
    print("Initializing printer...")
    if printer.initialize():
        print("✅ Printer initialized successfully")
    else:
        print("❌ Failed to initialize printer")
        if not use_mock:
            print(f"\nTroubleshooting:")
            print(f"  1. Check if printer is powered on")
            print(f"  2. Check network connection: ping {TSC_PRINTER_IP}")
            print(f"  3. Check if printer IP is correct in .env file")
            print(f"  4. Check if printer is on the same network")
        return False

    print()

    # Get printer status
    print("Getting printer status...")
    status = printer.get_status()
    print(f"Status: {status}")
    print()

    # Sample label data (based on SC-20GL from the PDF)
    test_labels = [
        {
            'name': 'Studio Classic 20ft Goldline',
            'data': {
                'series': 'Studio Series',
                'length': '20',
                'color_pattern': 'Goldline',
                'connector_type': 'Straight',
                'sku': 'SC-20GL'
            }
        },
        {
            'name': 'Studio Patch 3ft Black',
            'data': {
                'series': 'Studio Series',
                'length': '3',
                'color_pattern': 'Black',
                'connector_type': 'Straight',
                'sku': 'SP-03BK'
            }
        },
        {
            'name': 'MISC Cable with Custom Description',
            'data': {
                'series': 'Studio Series',
                'length': '15',
                'color_pattern': 'Miscellaneous',
                'connector_type': 'TS-TRS',
                'sku': 'SC-MISC',
                'description': 'Custom putty houndstooth with gold connectors'
            }
        }
    ]

    # Print test labels
    for i, test_label in enumerate(test_labels, 1):
        print(f"Test {i}: {test_label['name']}")
        print("-" * 40)

        # Create print job
        print_job = PrintJob(
            template="cable_label",
            data=test_label['data'],
            quantity=1
        )

        # Show what will be printed
        print("Label data:")
        for key, value in test_label['data'].items():
            print(f"  {key}: {value}")
        print()

        # Ask for confirmation
        if not use_mock:
            response = input("Print this label? (y/n/q): ").strip().lower()
            if response == 'q':
                print("Quitting test")
                break
            elif response != 'y':
                print("Skipped")
                print()
                continue

        # Print the label
        print("Sending to printer...")
        if printer.print_labels(print_job):
            print("✅ Label sent successfully")
        else:
            print("❌ Failed to send label")

        print()

    # Close printer connection
    printer.close()
    print("Printer connection closed")
    print()
    print("=" * 60)
    print("Test complete")
    print("=" * 60)

    return True


if __name__ == "__main__":
    # Check for --mock flag
    use_mock = "--mock" in sys.argv

    try:
        test_label_printer(use_mock=use_mock)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
