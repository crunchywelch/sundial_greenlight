#!/usr/bin/env python3
"""
Print retail SHELF labels (box side) on the TSC TE210.

The shelf label is the counterpart to the box label. A boxed cable carries the
pattern sticker on the front and the 2"x3" UPC label on the back, but neither
is visible once boxes are racked spine-out, so this is the one a browsing
customer actually reads. Its top line is the whole glance -- "20 FT
Instrument", both halves at the largest size the TE210 has.

Everything on it comes from catalog/ via `cable_config.describe_variant()` --
no Postgres, no Shopify -- so it prints with the tunnel down. It runs on the
ordinary 1" x 3" cable roll, NOT the 2" box stock, so no media swap.

Usage:
    python tools/printer/print_shelf_label.py SC-20GL --preview
    python tools/printer/print_shelf_label.py SC-20GL --count 12
    python tools/printer/print_shelf_label.py SC-20GL --pattern "Phish 2026"
    python tools/printer/print_shelf_label.py SC-20GL --mock

Options:
    --length      Override the big length (e.g. "20 FT")
    --type        Override the big cable type ("Instrument", "Microphone")
    --brand       Override the top row ("Sundial Audio Studio Series")
    --pattern     Override the pattern row ("Goldline")
    --connector   Override the connector row ("TS-TS - Canare GS-6")
    --no-sku      Leave the corner SKU off (pure customer-facing label)
    --count       Number of labels to print (default 1)
    --width-mm    Label stock width  (default 76.2 = 3")
    --height-mm   Label stock height (default 25.4 = 1")
    --preview     Show the resolved content and TSPL, print nothing
    --mock        Use the mock printer (no hardware)
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, MockTSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob
from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT
from greenlight.cable_config import describe_variant

# The rows the template prints, and the flags that override them.
_ROW_KEYS = ("brand_line", "pattern", "spec_line", "connector_line")
_ROW_FLAGS = ("brand", "pattern", "spec", "connector")


def build_data(args):
    """Assemble the shelf_label template data, or exit with a clear message."""
    data = {}
    if args.sku:
        data = describe_variant(args.sku)
        if data is None:
            sys.exit(f"Error: {args.sku!r} is not a variant SKU this catalog "
                     f"knows (expected e.g. SC-20GL, TV-12NJ, SC-25EH-R).")
        if data["kind"] != "catalog":
            print(f"  NOTE: {args.sku} is a {data['kind'].upper()} build, not a "
                  f"catalog variant. Retail boxes are catalog variants; this "
                  f"will print, but check the wording.\n")

    for key, val in (("brand_line", args.brand), ("pattern", args.pattern),
                     ("spec_line", args.spec),
                     ("connector_line", args.connector)):
        if val is not None:
            data[key] = val

    if args.no_sku:
        data["sku"] = ""

    if not any(data.get(k) for k in _ROW_KEYS + ("sku",)):
        sys.exit("Error: give a variant SKU (e.g. SC-20GL), or at least one of "
                 + " / ".join("--" + f for f in _ROW_FLAGS))
    return data


def describe(data):
    print()
    for key, label in (("brand_line", "Brand"), ("pattern", "Pattern"),
                       ("spec_line", "Spec"),
                       ("connector_line", "Connector"), ("sku", "SKU")):
        if data.get(key):
            print(f"  {label + ':':11}{data[key]}")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Print retail shelf labels for the side of a cable box.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sku", nargs="?", help="Variant SKU, e.g. SC-20GL")
    parser.add_argument("--brand", default=None,
                        help='Override the top row, e.g. "Sundial Audio"')
    parser.add_argument("--pattern", default=None,
                        help='Override the pattern row, e.g. "Goldline"')
    parser.add_argument("--spec", default=None,
                        help="Override the spec row, e.g. 20' Instrument Cable")
    parser.add_argument("--connector", default=None,
                        help='Override the connector row, e.g. "TS-TS"')
    parser.add_argument("--no-sku", action="store_true", dest="no_sku",
                        help="Leave the corner SKU off")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of labels to print (default 1)")
    parser.add_argument("--width-mm", type=float, default=76.2,
                        dest="width_mm", help="Stock width in mm (default 76.2)")
    parser.add_argument("--height-mm", type=float, default=25.4,
                        dest="height_mm", help="Stock height in mm (default 25.4)")
    parser.add_argument("--preview", action="store_true",
                        help="Show the resolved content and TSPL, print nothing")
    parser.add_argument("--mock", action="store_true",
                        help="Use the mock printer (no hardware)")

    args = parser.parse_args()
    if not (args.sku or args.brand or args.pattern or args.spec
            or args.connector):
        parser.print_help()
        return 1

    data = build_data(args)

    if args.preview:
        # Build the generator directly; never opens a socket.
        printer = TSCLabelPrinter(
            ip_address="preview", port=TSC_PRINTER_PORT,
            label_width_mm=args.width_mm, label_height_mm=args.height_mm,
        )
        describe(data)
        tspl = printer._generate_shelf_label_tspl(data).decode("latin-1")
        print("TSPL commands:\n")
        for line in tspl.split("\r\n"):
            if line:
                print("  " + line)
        print()
        return 0

    if args.mock:
        print("Using MOCK printer (no actual hardware)")
        printer = MockTSCLabelPrinter(ip_address=TSC_PRINTER_IP,
                                      port=TSC_PRINTER_PORT)
    else:
        printer = TSCLabelPrinter(
            ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT,
            label_width_mm=args.width_mm, label_height_mm=args.height_mm,
        )

    print("Initializing printer...")
    if not printer.initialize():
        print("Failed to initialize printer")
        if not args.mock:
            print("\nTroubleshooting:")
            print("  1. Check if printer is powered on")
            print(f"  2. Check network connection: ping {TSC_PRINTER_IP}")
            print("  3. Check printer IP in .env (GREENLIGHT_TSC_PRINTER_IP)")
        return 1

    describe(data)
    print(f"  Count:     {args.count}")
    print(f"  Stock:     {args.width_mm} x {args.height_mm} mm "
          f"(the standard cable roll)")
    print()

    if not args.mock:
        if input(f"Print {args.count} label(s)? (y/n): ").strip().lower() != "y":
            print("Cancelled")
            printer.close()
            return 0

    # One job, not a loop: TSPL `PRINT m,n` does the copies, so this is a
    # single connection rather than one per label.
    job = PrintJob(template="shelf_label", data=data, quantity=args.count)
    ok = printer.print_labels(job)
    if not ok:
        print("Failed to send the print job")

    if ok:
        print(f"Sent {args.count} label(s) successfully")
    printer.close()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
