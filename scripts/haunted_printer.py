#!/usr/bin/env python3
"""
Haunted Printer - Print creepy messages on the TSC label printer remotely.

The TSC TE210 only supports built-in bitmap fonts, so Unicode zalgo won't render.
Instead we create a "possessed" effect by overlapping text at random offsets,
mixing font sizes, and repeating characters with slight jitter.

Usage:
    python scripts/haunted_printer.py "HELP ME"
    python scripts/haunted_printer.py "I SEE YOU" --style glitch
    python scripts/haunted_printer.py "BEHIND YOU" --style scatter
    python scripts/haunted_printer.py  # random message from built-in list
    python scripts/haunted_printer.py --count 3  # print 3 labels in a row
"""

import argparse
import os
import random
import socket
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT

PRINTER_HOST = TSC_PRINTER_IP
PRINTER_PORT = TSC_PRINTER_PORT

# Label dimensions (1" x 3" at 203 DPI)
LABEL_WIDTH_MM = 76.2
LABEL_HEIGHT_MM = 25.4
LABEL_WIDTH_DOTS = 609
LABEL_HEIGHT_DOTS = 203

CREEPY_MESSAGES = [
    "HELP ME",
    "I SEE YOU",
    "BEHIND YOU",
    "IT'S INSIDE",
    "DON'T TURN AROUND",
    "CAN YOU HEAR IT",
    "THE CABLES REMEMBER",
    "WE ARE WATCHING",
    "LET ME OUT",
    "IT'S IN THE WALLS",
    "NOT ALONE",
    "WHO IS TESTING",
    "THE PRINTER HUNGERS",
    "FEED ME LABELS",
    "ERROR IN SOUL",
    "RUN",
    "LOOK UP",
    "COLD IN HERE",
    "DO YOU SMELL THAT",
    "CHECK THE BASEMENT",
]


def tspl_preamble():
    """Standard TSPL setup commands."""
    return [
        f"SIZE {LABEL_WIDTH_MM:.1f} mm, {LABEL_HEIGHT_MM:.1f} mm",
        "GAP 2 mm, 2 mm",
        "DIRECTION 1,0",
        "REFERENCE 0,0",
        "SET TEAR ON",
        "SET PEEL OFF",
        "CLS",
        "DENSITY 12",
        "SPEED 2",
    ]


def style_glitch(message):
    """Overlapping text with random offsets - looks like a printing malfunction."""
    cmds = tspl_preamble()

    # Base layer - main text, slightly off-center
    base_x = random.randint(10, 40)
    base_y = random.randint(60, 90)
    cmds.append(f'TEXT {base_x},{base_y},"4",0,1,1,"{message}"')

    # Ghost layers - same text repeated with small random offsets
    for _ in range(random.randint(3, 6)):
        dx = random.randint(-8, 8)
        dy = random.randint(-6, 6)
        font = random.choice(["2", "3", "4"])
        cmds.append(f'TEXT {base_x + dx},{base_y + dy},"{font}",0,1,1,"{message}"')

    # Random fragments scattered around
    for _ in range(random.randint(2, 5)):
        fragment = random.choice(list(message.replace(" ", "")))
        fx = random.randint(5, LABEL_WIDTH_DOTS - 30)
        fy = random.randint(5, LABEL_HEIGHT_DOTS - 30)
        font = random.choice(["1", "2", "3"])
        cmds.append(f'TEXT {fx},{fy},"{font}",0,1,1,"{fragment}"')

    # Glitch bars
    for _ in range(random.randint(1, 3)):
        bx = random.randint(0, LABEL_WIDTH_DOTS - 100)
        by = random.randint(0, LABEL_HEIGHT_DOTS - 5)
        bw = random.randint(30, 200)
        bh = random.randint(1, 4)
        cmds.append(f'BAR {bx},{by},{bw},{bh}')

    cmds.append("PRINT 1")
    cmds.append("")
    return cmds


def style_scatter(message):
    """Characters wobble around a baseline - like shaky handwriting."""
    cmds = tspl_preamble()

    baseline_y = 70
    chars = list(message)
    x = 15
    for ch in chars:
        if ch == " ":
            x += random.randint(20, 35)
            continue
        y = baseline_y + random.randint(-25, 25)
        font = random.choice(["3", "3", "4"])  # mostly same size, occasional larger
        cmds.append(f'TEXT {x},{y},"{font}",0,1,1,"{ch}"')
        x += random.randint(25, 38)
        if x > LABEL_WIDTH_DOTS - 30:
            break

    # Occasional inverted block
    if random.random() > 0.5:
        rx = random.randint(0, LABEL_WIDTH_DOTS - 80)
        ry = random.randint(0, LABEL_HEIGHT_DOTS - 30)
        cmds.append(f'REVERSE {rx},{ry},80,25')

    cmds.append("PRINT 1")
    cmds.append("")
    return cmds


def style_redrum(message):
    """Repeating message getting bigger, like writing on a wall."""
    cmds = tspl_preamble()

    y = 8
    fonts = ["1", "2", "3", "4", "5"]
    for i, font in enumerate(fonts):
        if y > LABEL_HEIGHT_DOTS - 15:
            break
        x = random.randint(5, 30)
        cmds.append(f'TEXT {x},{y},"{font}",0,1,1,"{message}"')
        y += [18, 22, 28, 35, 45][i]

    cmds.append("PRINT 1")
    cmds.append("")
    return cmds


def style_static(message):
    """Message buried in noise bars - like a haunted TV."""
    cmds = tspl_preamble()

    # Random noise bars across the whole label
    for _ in range(random.randint(15, 30)):
        bx = random.randint(0, LABEL_WIDTH_DOTS - 10)
        by = random.randint(0, LABEL_HEIGHT_DOTS - 3)
        bw = random.randint(5, 120)
        bh = random.randint(1, 3)
        cmds.append(f'BAR {bx},{by},{bw},{bh}')

    # Message in the middle, white text on dark background
    msg_y = LABEL_HEIGHT_DOTS // 2 - 15
    # Dark band behind text
    cmds.append(f'BAR 0,{msg_y - 5},{LABEL_WIDTH_DOTS},35')
    # Reverse the text area to make white-on-black
    cmds.append(f'TEXT 20,{msg_y},"4",0,1,1,"{message}"')
    cmds.append(f'REVERSE 0,{msg_y - 5},{LABEL_WIDTH_DOTS},35')

    # More noise on top
    for _ in range(random.randint(5, 10)):
        bx = random.randint(0, LABEL_WIDTH_DOTS - 10)
        by = random.randint(0, LABEL_HEIGHT_DOTS - 3)
        bw = random.randint(3, 60)
        bh = random.randint(1, 2)
        cmds.append(f'BAR {bx},{by},{bw},{bh}')

    cmds.append("PRINT 1")
    cmds.append("")
    return cmds


STYLES = {
    "glitch": style_glitch,
    "scatter": style_scatter,
    "redrum": style_redrum,
    "static": style_static,
}


def send_to_printer(cmds, host=PRINTER_HOST, port=PRINTER_PORT):
    """Send TSPL commands to printer via raw socket."""
    data = "\r\n".join(cmds).encode("utf-8")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        sock.sendall(data)
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError) as e:
        print(f"Failed to connect to printer at {host}:{port}: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Print creepy messages on the label printer")
    parser.add_argument("message", nargs="?", default=None, help="Message to print (random if omitted)")
    parser.add_argument("--style", choices=list(STYLES.keys()) + ["random"], default="random",
                        help="Visual style (default: random)")
    parser.add_argument("--count", type=int, default=1, help="Number of labels to print")
    parser.add_argument("--host", default=PRINTER_HOST, help=f"Printer hostname (default: {PRINTER_HOST})")
    parser.add_argument("--port", type=int, default=PRINTER_PORT, help=f"Printer port (default: {PRINTER_PORT})")
    parser.add_argument("--dry-run", action="store_true", help="Print TSPL commands to stdout instead of sending")
    args = parser.parse_args()

    for i in range(args.count):
        message = args.message or random.choice(CREEPY_MESSAGES)

        if args.style == "random":
            style_name = random.choice(list(STYLES.keys()))
        else:
            style_name = args.style

        cmds = STYLES[style_name](message)

        if args.dry_run:
            print(f"--- Label {i + 1} ({style_name}) ---")
            print("\r\n".join(cmds))
        else:
            if send_to_printer(cmds, host=args.host, port=args.port):
                print(f"[{style_name}] {message}")
            else:
                sys.exit(1)


if __name__ == "__main__":
    main()
