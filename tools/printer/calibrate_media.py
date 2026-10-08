#!/usr/bin/env python3
"""
Calibrate the TSC TE210 for a new label stock, and check what it can print.

Run this after swapping the roll. Two things happen:

  1. The printer is told the new media size and asked to auto-detect the gap
     between labels (TSPL `GAPDETECT`). It feeds a few labels while measuring
     -- that is expected, not a fault.
  2. Optionally, an alignment label is printed: a border drawn just inside the
     stock edges plus rows of fixed-width characters, so you can see at a
     glance whether the printable area is where the templates assume and
     whether the font advance is right.

Note `printer_setup.sh` is a different job: it switches a factory-fresh
printer out of ZPL mode into TSPL. Its "calibration" step only sets SIZE and
GAP -- it never runs a sensor detect, which is why this exists.

Usage:
    # 2" x 3" retail box stock (the default)
    python tools/printer/calibrate_media.py

    # the 1" x 3" cable roll
    python tools/printer/calibrate_media.py --cable-roll

    # any other stock
    python tools/printer/calibrate_media.py --width-mm 76.2 --height-mm 38.1

    # show the TSPL without sending it
    python tools/printer/calibrate_media.py --dry-run

Options:
    --cable-roll    Shorthand for 1" x 3" (76.2 x 25.4 mm)
    --width-mm      Stock width in mm  (default 76.2 = 3")
    --height-mm     Stock height in mm (default 50.8 = 2")
    --gap-mm        Gap between labels; omit to auto-detect
    --no-detect     Skip the sensor detect, just set the media size
    --no-test       Skip the alignment label
    --dry-run       Print the TSPL and exit without connecting
"""

import argparse
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT
from greenlight.hardware.tsc_label_printer import TSCLabelPrinter

DPI = 203

# Gap between labels on ordinary die-cut stock. Used when --gap-mm is not
# given. NOT 0: `GAP 0,0` is TSPL for continuous media.
DEFAULT_GAP_MM = 2.0

# Rows for the alignment label: (font, character count). The point is to
# bracket the assumed advance -- TSCLabelPrinter.FONT_ADVANCE says font "2"
# advances 14 dots, so 41 characters should just fit inside the border and 44
# should cross it. That number was calibrated from a single printed label, so
# this is how it gets confirmed.
RULER_ROWS = [("2", 38), ("2", 41), ("2", 44),
              ("3", 30), ("3", 32),
              ("4", 20), ("4", 22)]
FONT_H = {"1": 12, "2": 20, "3": 24, "4": 32, "5": 48}


def header(width_mm, height_mm, shift=None, gap_mm=None):
    """The app's own per-stock setup (TSCLabelPrinter._media_header), so a
    measurement here is a measurement of what real labels print with.

    `shift` / `gap_mm` override it, for trying a correction before writing
    it into MEDIA_REGISTRATION.
    """
    cmds = TSCLabelPrinter._media_header(width_mm, height_mm)
    if shift is not None:
        cmds = [f"SHIFT {shift}" if c.startswith("SHIFT ") else c for c in cmds]
    if gap_mm is not None:
        offset = next(c for c in cmds if c.startswith("GAP ")).split(",")[1]
        cmds = [f"GAP {gap_mm:.1f} mm,{offset}" if c.startswith("GAP ") else c
                for c in cmds]
    return cmds + ["DENSITY 10", "SPEED 3"]


def media_commands(width_mm, height_mm, gap_mm, detect, shift=None):
    """TSPL to set the media size and (optionally) auto-detect the gap."""
    # GAP m,n -- m is the gap between labels, n is the gap offset, which this
    # printer DOES need on die-cut stock (see MEDIA_REGISTRATION). And m must
    # NOT be 0: `GAP 0,0` means continuous media, which leaves the printer
    # with no top-of-form to register against, so it prints wherever the
    # paper happens to sit. That put the first calibration ~50 dots low.
    cmds = header(width_mm, height_mm, shift=shift, gap_mm=gap_mm)
    if detect:
        # Feeds a few labels while measuring the gap, then stores the result.
        cmds.append("GAPDETECT")
    return cmds


def alignment_label(width_mm, height_mm):
    """A border drawn just inside the stock edges, plus the ruler rows."""
    w = int(width_mm * DPI / 25.4)
    h = int(height_mm * DPI / 25.4)
    x_left = 16

    cmds = header(width_mm, height_mm) + [
        # BOX x_start,y_start,x_end,y_end,thickness -- 2 dots in from each
        # edge, so anything touching it is off the printable area.
        f"BOX 2,2,{w - 3},{h - 3},2",
        f'TEXT {x_left},10,"2",0,1,1,'
        f'"MEDIA CHECK {width_mm:.1f} x {height_mm:.1f} mm = {w}x{h} dots"',
    ]

    y = 44
    for font, count in RULER_ROWS:
        if y + FONT_H[font] > h - 8:
            break
        cmds.append(f'TEXT {x_left},{y},"{font}",0,1,1,"{"#" * count}"')
        y += FONT_H[font] + 6

    cmds.append("PRINT 1")
    return cmds


# Compare rows: (font, character count). The count differs per font so every
# row's predicted end lands in roughly the same place, well inside the label
# -- a fixed 20 characters put font "5" at dot 700, off the stock entirely.
#
# Every font gets a row. The first version measured only "2" and extrapolated
# the rest as "cell width + 2", which was wrong for "3" and "4": they match
# the manual exactly and only "2" differs from it. There is no pattern to
# infer, so each one is measured.
MEASURE_ROWS = [("1", 40), ("2", 24), ("3", 20), ("4", 14), ("5", 10)]


def measurement_label(width_mm, height_mm, shift=None):
    """A label that measures the printable area and the font advance.

    Three things are being separated here, because a single border box
    conflates them: where the printable area actually starts and ends, how
    far the image is offset from the stock, and how wide a character really
    is. The rulers answer the first two; the compare rows answer the third
    without depending on either.
    """
    w = int(width_mm * DPI / 25.4)
    h = int(height_mm * DPI / 25.4)
    adv = TSCLabelPrinter.FONT_ADVANCE
    cmds = header(width_mm, height_mm, shift=shift)

    # Horizontal ruler: a tick every 50 dots, numbered every 100.
    for x in range(0, w, 50):
        tick = 14 if x % 100 == 0 else 8
        cmds.append(f"BAR {x},0,2,{tick}")
    for x in range(0, w, 100):
        cmds.append(f'TEXT {x + 4},16,"1",0,1,1,"{x}"')

    # Vertical ruler down the left edge: a tick every 50 dots, numbered.
    for y in range(50, h, 50):
        cmds.append(f"BAR 0,{y},14,2")
        cmds.append(f'TEXT 18,{y - 6},"1",0,1,1,"{y}"')

    # Compare rows. A vertical line is drawn at exactly where
    # MEASURE_CHARS characters should end, running above and below the text,
    # so the only judgement needed is "does the text reach the line". That is
    # far easier to read than comparing two right-hand edges, and it cannot
    # be confused by a registration offset or by edge clipping.
    y = 44
    x0 = 60
    for font, count in MEASURE_ROWS:
        if y + FONT_H[font] + 16 > h:
            break
        cmds.append(f'TEXT {x0},{y},"{font}",0,1,1,"{"#" * count}"')
        edge = x0 + count * adv[font]
        cmds.append(f"BAR {edge},{y - 8},2,{FONT_H[font] + 16}")
        y += FONT_H[font] + 18

    # Fine ruler over the last 80 dots, every 10, to pin where the printable
    # area actually ends -- the 50-dot ruler only narrowed it to 352..400, and
    # box_label anchors the UPC's human-readable digits off the bottom edge.
    #
    # It lives on the RIGHT: the first version put it at x=0 on top of the
    # 50-dot ruler, and their numbers overprinted into an unreadable mess
    # right in the range being measured.
    for yy in range(h - 80, h, 10):
        cmds.append(f"BAR {w - 26},{yy},26,2")
        cmds.append(f'TEXT {w - 62},{yy - 6},"1",0,1,1,"{yy}"')

    cmds.append("PRINT 1")
    return cmds


def send(ip, port, cmds):
    payload = ("\r\n".join(cmds) + "\r\n").encode("utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10.0)
    sock.connect((ip, port))
    sock.sendall(payload)
    sock.close()
    return len(payload)


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate the TE210 for a new label stock.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cable-roll", action="store_true", dest="cable_roll",
                        help='Shorthand for the 1" x 3" cable roll')
    parser.add_argument("--width-mm", type=float, default=76.2, dest="width_mm")
    parser.add_argument("--height-mm", type=float, default=50.8, dest="height_mm")
    parser.add_argument("--gap-mm", type=float, default=None, dest="gap_mm",
                        help=f"Gap between labels in mm (default "
                             f"{DEFAULT_GAP_MM}); GAPDETECT then measures it")
    parser.add_argument("--measure", action="store_true",
                        help="Print the measurement label only (no detect): "
                             "rulers for the printable area, plus text-vs-bar "
                             "rows that pin the font advance")
    parser.add_argument("--shift", type=int, default=None,
                        help="TSPL SHIFT in dots, to correct a vertical "
                             "registration offset. Sign is determined "
                             "empirically -- try one, reprint, compare.")
    parser.add_argument("--no-detect", action="store_true", dest="no_detect")
    parser.add_argument("--no-test", action="store_true", dest="no_test")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    args = parser.parse_args()

    if args.cable_roll:
        args.width_mm, args.height_mm = 76.2, 25.4

    w = int(args.width_mm * DPI / 25.4)
    h = int(args.height_mm * DPI / 25.4)
    detect = not args.no_detect

    print()
    print(f"  Printer:  {TSC_PRINTER_IP}:{TSC_PRINTER_PORT}")
    print(f"  Stock:    {args.width_mm} x {args.height_mm} mm "
          f"({w} x {h} dots @ {DPI} DPI)")
    gap_shown = DEFAULT_GAP_MM if args.gap_mm is None else args.gap_mm
    print(f"  Gap:      {gap_shown} mm, offset 0"
          f"{' + GAPDETECT' if detect else ''}")
    print()

    if args.measure:
        detect = False
    media = ([] if args.measure
             else media_commands(args.width_mm, args.height_mm,
                                 args.gap_mm, detect, args.shift))
    if args.measure:
        test = measurement_label(args.width_mm, args.height_mm, args.shift)
    elif args.no_test:
        test = []
    else:
        test = alignment_label(args.width_mm, args.height_mm)

    if args.dry_run:
        print("  Media commands:")
        for c in media:
            print(f"    {c}")
        if test:
            print("\n  Alignment label:")
            for c in test:
                print(f"    {c}")
        print()
        return 0

    if detect:
        print("  The printer will feed a few labels while it measures the")
        print("  gap. That is the calibration working, not a fault.")
        print()
    if input("  Go? (y/n): ").strip().lower() != "y":
        print("  Cancelled")
        return 0

    try:
        if media:
            send(TSC_PRINTER_IP, TSC_PRINTER_PORT, media)
            print(f"\n  Sent media setup{' + GAPDETECT' if detect else ''}.")
            if test:
                input("  Press Enter once the printer has stopped feeding...")
        if test:
            send(TSC_PRINTER_IP, TSC_PRINTER_PORT, test)
            print("  Sent the label.")
    except (socket.timeout, socket.error, OSError) as e:
        print(f"\n  Failed to reach the printer: {e}")
        print(f"  Check: ping {TSC_PRINTER_IP}")
        return 1

    if args.measure:
        adv = TSCLabelPrinter.FONT_ADVANCE
        print()
        print("  Read it back to me as three answers:")
        print()
        print("  1. HORIZONTAL RULER (top edge, numbered every 100 dots)")
        print(f"       lowest number you can see, and the highest "
              f"(declared width is {w})")
        print("  2. VERTICAL RULER (left edge, numbered every 50 dots)")
        print(f"       lowest and highest number visible "
              f"(declared height is {h})")
        print("  3. COMPARE ROWS: each row of # has a VERTICAL LINE drawn")
        print("     where it is predicted to end. For each row: does the")
        print("     text STOP SHORT of the line, END EXACTLY at it, or")
        print("     CROSS it?")
        for i, (font, count) in enumerate(MEASURE_ROWS, 1):
            print(f'       row {i}: font "{font}", {count} chars, '
                  f'line at dot {60 + count * adv[font]}')
        print()
        print("  4. FINE RULER bottom-RIGHT, every 10 dots: the LAST number")
        print(f"     you can read (declared height is {h}).")
        print()
        print("  Rows 1, 2 and 4 give the real printable area. Row 3 gives")
        print("  the font advance and is unaffected by either -- which is")
        print("  why the border box alone could not settle it.")
        print()
    elif test:
        adv = TSCLabelPrinter.FONT_ADVANCE
        print()
        print("  On the alignment label, top to bottom:")
        print()
        for font, count in RULER_ROWS:
            end = 16 + count * adv[font]
            verdict = "should FIT" if end <= w - 3 else "should CROSS the border"
            print(f'    font "{font}"  {count:2} chars  '
                  f'(ends at dot {end:3} of {w})  {verdict}')
        print()
        print("  If a row that should fit crosses the border, or one that")
        print("  should cross stays inside, then FONT_ADVANCE is wrong for")
        print(f'  that font -- it is currently {adv}.')
        print("  Everything that places text by character count depends on it:")
        print("  greenlight/hardware/tsc_label_printer.py FONT_ADVANCE.")
        print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
