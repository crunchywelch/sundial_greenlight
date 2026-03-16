#!/usr/bin/env python3
"""
Test script for TSC TE210 label printer

This script tests the label printer by:
1. Connecting to the printer
2. Generating TSPL commands for a sample label
3. Sending the label to the printer

Usage:
    python test_label_printer.py [--mock]
    python test_label_printer.py --text "AA:BB:CC:DD:EE:FF"
    python test_label_printer.py --text "MAC: AA:BB:CC:DD" --title "Tablet 3"
    python test_label_printer.py --text "line one" "line two" "line three"

Options:
    --mock    Use mock printer (no actual hardware)
    --text    Print arbitrary text on a label (remaining args are lines)
    --title   Optional bold header line (used with --text)
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, MockTSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob
from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM


def create_printer(use_mock=False):
    """Create and initialize a printer instance"""
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

    print("Initializing printer...")
    if printer.initialize():
        print("Printer initialized successfully")
        return printer
    else:
        print("Failed to initialize printer")
        if not use_mock:
            print(f"\nTroubleshooting:")
            print(f"  1. Check if printer is powered on")
            print(f"  2. Check network connection: ping {TSC_PRINTER_IP}")
            print(f"  3. Check if printer IP is correct in .env file")
            print(f"  4. Check if printer is on the same network")
        return None


def print_text_label(lines, title=None, use_mock=False):
    """Print a simple text label with arbitrary content"""
    printer = create_printer(use_mock)
    if not printer:
        return False

    data = {'lines': lines}
    if title:
        data['title'] = title

    print()
    if title:
        print(f"Title: {title}")
    for line in lines:
        print(f"  {line}")
    print()

    if not use_mock:
        response = input("Print this label? (y/n): ").strip().lower()
        if response != 'y':
            print("Cancelled")
            printer.close()
            return False

    print_job = PrintJob(template="text_label", data=data, quantity=1)
    print("Sending to printer...")
    success = printer.print_labels(print_job)
    if success:
        print("Label sent successfully")
    else:
        print("Failed to send label")

    printer.close()
    return success


def test_label_printer(use_mock=False):
    """Test the TSC label printer with sample cable labels"""

    print("=" * 60)
    print("TSC TE210 Label Printer Test")
    print("=" * 60)
    print()

    printer = create_printer(use_mock)
    if not printer:
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
            print("Label sent successfully")
        else:
            print("Failed to send label")

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
    parser = argparse.ArgumentParser(description="TSC TE210 Label Printer Test")
    parser.add_argument("--mock", action="store_true", help="Use mock printer")
    parser.add_argument("--text", nargs="+", metavar="LINE",
                        help="Print a text label with arbitrary content (each arg is a line)")
    parser.add_argument("--title", type=str, default=None,
                        help="Bold title line for text labels")

    args = parser.parse_args()

    try:
        if args.text:
            print_text_label(args.text, title=args.title, use_mock=args.mock)
        else:
            test_label_printer(args.mock)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
