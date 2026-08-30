#!/usr/bin/env python3
"""
Print California Proposition 65 warning labels on the TSC TE210.

Prop 65 labels require the exclamation-point warning triangle. The TE210 only
renders built-in bitmap fonts, so the triangle is rasterized as a bitmap by the
printer driver (template "prop65_label") rather than printed as a glyph.

Usage:
    python util/printer/print_prop65.py                      # short form, both endpoints
    python util/printer/print_prop65.py --chemical lead      # name a chemical
    python util/printer/print_prop65.py --form long          # full warning statement
    python util/printer/print_prop65.py --endpoints cancer   # cancer only
    python util/printer/print_prop65.py --count 10           # print 10 copies
    python util/printer/print_prop65.py --preview            # ASCII/TSPL preview, no printing
    python util/printer/print_prop65.py --mock               # dry-run via mock printer

Options:
    --form        "short" (default) or "long" (full statement)
    --chemical    Chemical name to cite (e.g. lead, DEHP). Optional.
    --endpoints   "both" (default), "cancer", or "reproductive"
    --count       Number of copies to print (default 1)
    --preview     Render the triangle + TSPL to the terminal without printing
    --mock        Use the mock printer (no hardware)

With no printable action and no arguments, prints a short-form label; use
--preview first if you want to see it before sending.
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, MockTSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob
from greenlight.config import (
    TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM,
)


def build_data(args):
    return {
        'form': args.form,
        'chemical': args.chemical,
        'endpoints': args.endpoints,
        'quantity': args.count,
    }


def preview(data):
    """Render the warning triangle as ASCII and dump the TSPL, no printing."""
    printer = TSCLabelPrinter(
        ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT,
        label_width_mm=TSC_LABEL_WIDTH_MM, label_height_mm=TSC_LABEL_HEIGHT_MM,
    )

    tri = printer._generate_warning_triangle_bitmap(height=64, border=7)
    W, H, wb, raw = tri['width'], tri['height'], tri['width_bytes'], tri['data']
    print(f"\nWarning triangle preview ({W}x{H} dots):\n")
    for y in range(H):
        row = raw[y * wb:(y + 1) * wb]
        print(''.join('#' if (row[x // 8] >> (7 - (x % 8))) & 1 else ' '
                      for x in range(W)))

    tspl = printer._generate_prop65_label_tspl(data)
    print("\nTSPL commands (bitmap bytes shown as <BITMAP N bytes>):\n")
    text = tspl.decode('latin-1')
    # Collapse the raw bitmap blob so the TSPL stays readable.
    import re
    text = re.sub(r'(BITMAP [^,]+,[^,]+,[^,]+,[^,]+,0,).*?(\r\nPRINT)',
                  lambda m: f"{m.group(1)}<bitmap bytes>{m.group(2)}", text,
                  flags=re.S)
    for line in text.splitlines():
        print(f"  {line}")
    print()


def describe(data):
    print()
    print("Prop 65 warning label:")
    print(f"  Form:      {data['form']}")
    print(f"  Endpoints: {data['endpoints']}")
    print(f"  Chemical:  {data['chemical'] or '(none named)'}")
    print(f"  Copies:    {data['quantity']}")
    print()


def create_printer(use_mock):
    if use_mock:
        print("Using MOCK printer (no actual hardware)")
        printer = MockTSCLabelPrinter(ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT)
    else:
        print(f"Using REAL printer at {TSC_PRINTER_IP}:{TSC_PRINTER_PORT}")
        printer = TSCLabelPrinter(
            ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT,
            label_width_mm=TSC_LABEL_WIDTH_MM, label_height_mm=TSC_LABEL_HEIGHT_MM,
        )
    print("Initializing printer...")
    if printer.initialize():
        print("Printer initialized successfully")
        return printer
    print("Failed to initialize printer")
    if not use_mock:
        print(f"\nTroubleshooting:")
        print(f"  1. Check if printer is powered on")
        print(f"  2. Check network connection: ping {TSC_PRINTER_IP}")
        print(f"  3. Check the printer IP in .env")
    return None


def print_label(data, use_mock):
    printer = create_printer(use_mock)
    if not printer:
        return False

    describe(data)

    if not use_mock:
        response = input(f"Print {data['quantity']} label(s)? (y/n): ").strip().lower()
        if response != 'y':
            print("Cancelled")
            printer.close()
            return False

    job = PrintJob(template="prop65_label", data=data, quantity=data['quantity'])
    print("Sending to printer...")
    success = printer.print_labels(job)
    print("Label sent successfully" if success else "Failed to send label")
    printer.close()
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Print California Proposition 65 warning labels on the TSC TE210.")
    parser.add_argument("--form", choices=["short", "long"], default="short",
                        help="Short form (default) or the full warning statement")
    parser.add_argument("--chemical", type=str, default=None,
                        help="Chemical name to cite (e.g. lead, DEHP)")
    parser.add_argument("--endpoints", choices=["both", "cancer", "reproductive"],
                        default="both", help="Harm endpoint(s) to state (default both)")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of copies to print (default 1)")
    parser.add_argument("--preview", action="store_true",
                        help="Render the triangle + TSPL to the terminal without printing")
    parser.add_argument("--mock", action="store_true",
                        help="Use the mock printer (no hardware)")

    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be at least 1")
    data = build_data(args)

    try:
        if args.preview:
            preview(data)
        else:
            print_label(data, args.mock)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
