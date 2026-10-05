#!/usr/bin/env python3
"""
Print retail box labels (with UPC-A barcode) on the TSC TE210.

The UPC comes from Shopify's variant `barcode` field, which is the source of
truth for retail UPCs — there is no UPC column in Postgres. Pass a variant SKU
and the script looks up the UPC and product name; pass --upc to bypass Shopify
entirely (useful for previewing before the UPCs are loaded).

Box labels use TALLER stock than the 1" x 3" cable roll: 2" x 3" by default.
At 203 DPI a UPC-A only renders at whole-dot module widths, so 2" stock prints
at 113.7% magnification (comfortably in spec) while 1" stock is forced down to
75.8% — the absolute GS1 floor for thermal printing, with no room for branding.
Use --preview to see exactly what a given stock size yields before printing.

Usage:
    python tools/printer/print_box_label.py SC-20GL --preview
    python tools/printer/print_box_label.py SC-20GL --count 12
    python tools/printer/print_box_label.py --upc 036000291452 \
        --title "Studio Classic" --subtitle "20 ft - Goldline" --preview
    python tools/printer/print_box_label.py SC-20GL --height-mm 25.4 --preview
    python tools/printer/print_box_label.py SC-20GL --mock

Options:
    --upc         Use this GTIN-12 instead of looking it up in Shopify
    --title       Override the product name line
    --subtitle    Override the spec line (length / pattern / connector)
    --count       Number of labels to print (default 1)
    --width-mm    Label stock width  (default 76.2 = 3")
    --height-mm   Label stock height (default 50.8 = 2")
    --preview     Render the TSPL and a geometry report, print nothing
    --mock        Use the mock printer (no hardware)
"""

import sys
import os
import argparse
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from greenlight.hardware.tsc_label_printer import TSCLabelPrinter, MockTSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob
from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT
from greenlight.gtin import validate_gtin12, normalize_gtin12


def resolve_from_shopify(variant_sku):
    """Fetch UPC + product naming for a variant SKU from the audio store.

    Returns (data_dict, error_message). data_dict is None on failure.
    """
    from greenlight.shopify_client import get_audio_variant_by_sku

    variant = get_audio_variant_by_sku(variant_sku)
    if not variant:
        return None, (f"SKU {variant_sku} not found in the audio Shopify store. "
                      f"Create the variant first, or pass --upc to preview.")

    if not variant.get("barcode"):
        return None, (f"SKU {variant_sku} has no UPC in Shopify (barcode field "
                      f"is empty). Load it with tools/audio/audio_upc_sync.py, "
                      f"or pass --upc to preview.")

    variant_title = variant.get("variant_title") or ""
    if variant_title.lower() == "default title":
        variant_title = ""

    return {
        "upc": variant["barcode"],
        "product_title": variant.get("product_title") or variant_sku,
        "subtitle": variant_title,
        "sku": variant_sku,
    }, None


def build_data(args):
    """Assemble the box_label template data, or exit with a clear message."""
    if args.upc:
        upc = normalize_gtin12(args.upc)
        if not upc:
            # Re-validate the raw value so the user gets the specific reason.
            _, err = validate_gtin12(args.upc.strip())
            sys.exit(f"Error: {err}")
        data = {
            "upc": upc,
            "product_title": args.title or "",
            "subtitle": args.subtitle or "",
            "sku": args.sku or "",
        }
    else:
        if not args.sku:
            sys.exit("Error: give a variant SKU (e.g. SC-20GL) or --upc")
        data, err = resolve_from_shopify(args.sku)
        if err:
            sys.exit(f"Error: {err}")

    # Explicit overrides win over whatever Shopify supplied.
    if args.title:
        data["product_title"] = args.title
    if args.subtitle:
        data["subtitle"] = args.subtitle

    data["label_width_mm"] = args.width_mm
    data["label_height_mm"] = args.height_mm
    return data


# TSPL internal bitmap font heights in dots, for the geometry report.
_FONT_H = {"1": 12, "2": 20, "3": 24, "4": 32, "5": 48}
# Horizontal advance per character. NOT the manual's cell width -- see
# TSCLabelPrinter.FONT_ADVANCE, which this mirrors. The report used to check
# only the barcode band, so text running off the right edge was invisible
# here; that is how the brand block shipped overlapping the logo.
_FONT_W = TSCLabelPrinter.FONT_ADVANCE


def preview(printer, data):
    """Render the TSPL plus a geometry report; print nothing to hardware."""
    tspl = printer._generate_box_label_tspl(data)
    txt = tspl.decode("latin-1")

    print("\nTSPL commands:\n")
    for line in txt.split("\r\n"):
        if line.startswith("BITMAP"):
            print("  BITMAP <wire logo bitmap>")
        elif line:
            print("  " + line)

    bc = re.search(r'BARCODE (\d+),(\d+),"UPCA",(\d+),1,0,(\d+),', txt)
    size = re.search(r"SIZE ([\d.]+) mm, ([\d.]+) mm", txt)
    if not (bc and size):
        print("\n  (could not parse geometry)")
        return

    bx, by, bh, narrow = map(int, bc.groups())
    dpi = printer.dpi
    w_dots = int(float(size.group(1)) * dpi / 25.4)
    h_dots = int(float(size.group(2)) * dpi / 25.4)
    x_in = narrow / dpi
    mag = x_in / TSCLabelPrinter.UPCA_NOMINAL_X_IN
    bars_w = TSCLabelPrinter.UPCA_MODULES * narrow
    quiet_needed = 9 * narrow
    hri = 28

    print("\nGeometry:\n")
    print(f"  stock              {size.group(1)} x {size.group(2)} mm "
          f"({w_dots} x {h_dots} dots @ {dpi} DPI)")
    print(f"  module width (X)   {narrow} dots = {x_in * 25.4:.3f} mm")
    print(f"  magnification      {mag * 100:.1f}%", end="")
    if mag >= 0.80:
        print("   [in spec]")
    elif mag >= 0.75:
        print("   [thermal-print floor — legal but no margin]")
    else:
        print("   [BELOW SPEC — will not scan reliably]")
    print(f"  symbol             {bars_w} x {bh} dots at ({bx}, {by})")
    print(f"  quiet zones        left {bx}, right {w_dots - bx - bars_w} "
          f"dots (need {quiet_needed})")
    clearance = h_dots - by - bh - hri
    print(f"  bottom clearance   {clearance} dots below the digits", end="")
    print("   [digits were being cut off at 14]"
          if clearance >= TSCLabelPrinter.BOX_LABEL_BOTTOM_MARGIN else "")

    problems = []
    if bx < quiet_needed or (w_dots - bx - bars_w) < quiet_needed:
        problems.append("quiet zone too narrow")
    if by + bh + hri > h_dots:
        problems.append("barcode overflows the label")
    if mag < 0.75:
        problems.append("magnification below the 75% thermal floor")

    # Horizontal bounds and collisions. Every text box plus the logo bitmap,
    # measured with the real advance, so an over-wide row fails here instead
    # of on the stock.
    boxes = []
    for t in re.finditer(r'TEXT (\d+),(\d+),"(\d)",0,(\d+),(\d+),"([^"]*)"', txt):
        x, y_ = int(t.group(1)), int(t.group(2))
        xm, ym = int(t.group(4)), int(t.group(5))
        text = t.group(6)
        boxes.append((f"{text!r}", x, y_,
                      len(text) * _FONT_W[t.group(3)] * xm,
                      _FONT_H[t.group(3)] * ym))
    for b in re.finditer(r"BITMAP (\d+),(\d+),(\d+),(\d+),", txt):
        x, y_, wb, hb = (int(g) for g in b.groups())
        boxes.append(("wire logo", x, y_, wb * 8, hb))

    print("\nElements:\n")
    for label, x, y_, bw, bh_ in boxes:
        over = "  !! past the right edge" if x + bw > w_dots else ""
        print(f"  ({x:3},{y_:3}) {bw:3}x{bh_:<3} {label}{over}")
        if x + bw > w_dots:
            problems.append(f"{label} runs {x + bw - w_dots} dots past the "
                            f"right edge")
        if x < 2:
            problems.append(f"{label} starts off the left edge")

    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if (a[1] < b[1] + b[3] and b[1] < a[1] + a[3]
                    and a[2] < b[2] + b[4] and b[2] < a[2] + a[4]):
                problems.append(f"{a[0]} overlaps {b[0]}")

    # Overlap check: no text or rule may intrude into the barcode band.
    band = (by, by + bh + hri)
    for t in re.finditer(r'TEXT (\d+),(\d+),"(\d)",0,(\d+),(\d+),"([^"]*)"', txt):
        top = int(t.group(2))
        bottom = top + _FONT_H[t.group(3)] * int(t.group(5))
        if top < band[1] and bottom > band[0]:
            problems.append(f"text {t.group(6)[:24]!r} overlaps the barcode")
    for b in re.finditer(r"BAR (\d+),(\d+),(\d+),(\d+)", txt):
        top, h = int(b.group(2)), int(b.group(4))
        if top < band[1] and top + h > band[0]:
            problems.append("divider rule overlaps the barcode")

    print()
    if problems:
        for p in problems:
            print(f"  !! {p}")
    else:
        print("  All checks passed.")
    print()


def describe(data):
    print()
    print(f"  UPC:      {data['upc']}  (printer renders check digit "
          f"{data['upc'][11]})")
    if data.get("sku"):
        print(f"  SKU:      {data['sku']}")
    if data.get("product_title"):
        print(f"  Title:    {data['product_title']}")
    if data.get("subtitle"):
        print(f"  Subtitle: {data['subtitle']}")
    print(f"  Stock:    {data['label_width_mm']} x {data['label_height_mm']} mm")
    print()


def create_printer(use_mock, width_mm, height_mm):
    if use_mock:
        print("Using MOCK printer (no actual hardware)")
        return MockTSCLabelPrinter(ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT)
    printer = TSCLabelPrinter(
        ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT,
        label_width_mm=width_mm, label_height_mm=height_mm,
    )
    return printer


def main():
    parser = argparse.ArgumentParser(
        description="Print retail box labels with a UPC-A barcode.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sku", nargs="?", help="Variant SKU, e.g. SC-20GL")
    parser.add_argument("--upc", type=str, default=None,
                        help="Use this GTIN-12 instead of a Shopify lookup")
    parser.add_argument("--title", type=str, default=None,
                        help="Override the product name line")
    parser.add_argument("--subtitle", type=str, default=None,
                        help="Override the spec line")
    parser.add_argument("--count", type=int, default=1,
                        help="Number of labels to print (default 1)")
    parser.add_argument("--width-mm", type=float, default=76.2,
                        dest="width_mm", help="Stock width in mm (default 76.2)")
    parser.add_argument("--height-mm", type=float, default=50.8,
                        dest="height_mm", help="Stock height in mm (default 50.8)")
    parser.add_argument("--preview", action="store_true",
                        help="Render TSPL + geometry report without printing")
    parser.add_argument("--mock", action="store_true",
                        help="Use the mock printer (no hardware)")

    args = parser.parse_args()
    if not args.sku and not args.upc:
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
        preview(printer, data)
        return 0

    printer = create_printer(args.mock, args.width_mm, args.height_mm)
    print("Initializing printer...")
    if not printer.initialize():
        print("Failed to initialize printer")
        if not args.mock:
            print(f"\nTroubleshooting:")
            print(f"  1. Check if printer is powered on")
            print(f"  2. Check network connection: ping {TSC_PRINTER_IP}")
            print(f"  3. Check printer IP in .env (GREENLIGHT_TSC_PRINTER_IP)")
        return 1

    describe(data)
    print(f"  Count:    {args.count}")
    print()
    print(f"  NOTE: load {args.width_mm} x {args.height_mm} mm box stock and "
          f"calibrate before printing.")
    print()

    if not args.mock:
        if input(f"Print {args.count} label(s)? (y/n): ").strip().lower() != "y":
            print("Cancelled")
            printer.close()
            return 0

    ok = True
    for i in range(args.count):
        job = PrintJob(template="box_label", data=data, quantity=1)
        if not printer.print_labels(job):
            print(f"Failed on label {i + 1} of {args.count}")
            ok = False
            break

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
