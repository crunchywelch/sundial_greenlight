#!/usr/bin/env python3
"""
Print labels on the TSC TE210 label printer.

Primary use is printing arbitrary text labels (MAC addresses, asset tags,
notes, etc.). Also includes a --self-test that prints built-in sample cable
labels to verify the printer end to end.

Usage:
    python util/printer/print_label.py "AA:BB:CC:DD:EE:FF"
    python util/printer/print_label.py "MAC: AA:BB:CC:DD" --title "Tablet 3"
    python util/printer/print_label.py "line one" "line two" "line three"
    python util/printer/print_label.py "BIG LABEL" --scale 2
    python util/printer/print_label.py --self-test          # sample cable labels
    python util/printer/print_label.py --self-test --mock   # dry-run, no hardware

Options:
    --title      Optional bold header line
    --scale      Font size multiplier (default 1)
    --mock       Use mock printer (no actual hardware)
    --self-test  Print built-in sample cable labels
    --text       Deprecated alias for positional text lines

With no arguments, prints this help.
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

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


def print_text_label(lines, title=None, use_mock=False, scale=1):
    """Print a simple text label with arbitrary content"""
    printer = create_printer(use_mock)
    if not printer:
        return False

    data = {'lines': lines, 'scale': scale}
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


def run_self_test(use_mock=False):
    """Print built-in sample cable labels to verify the printer end to end."""

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
                'sku': 'SC-MISC-1',
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
    parser = argparse.ArgumentParser(
        description="Print arbitrary text labels on the TSC TE210 "
                    "(or run a printer self-test).")
    parser.add_argument("lines", nargs="*", metavar="LINE",
                        help="Text line(s) to print (each argument is one line)")
    parser.add_argument("--text", nargs="+", metavar="LINE",
                        help="Deprecated alias for positional LINE arguments")
    parser.add_argument("--title", type=str, default=None,
                        help="Bold title/header line")
    parser.add_argument("--scale", type=int, default=1,
                        help="Font size multiplier (default 1)")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock printer (no actual hardware)")
    parser.add_argument("--self-test", action="store_true",
                        help="Print built-in sample cable labels to verify the printer")

    args = parser.parse_args()
    lines = args.text or args.lines

    try:
        if args.self_test:
            run_self_test(args.mock)
        elif lines:
            print_text_label(lines, title=args.title, use_mock=args.mock,
                             scale=args.scale)
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
