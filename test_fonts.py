#!/usr/bin/env python3
"""
Test different fonts available on the TSC TE210 printer

This script prints a sample label showing all available fonts
so you can choose which ones look best.

Usage:
    python test_fonts.py
"""

import sys
import os
import socket

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM


def print_font_samples(printer_ip, printer_port):
    """Print label with font samples"""

    print("=" * 70)
    print("TSC TE210 Font Test")
    print("=" * 70)
    print()
    print(f"Printer: {printer_ip}:{printer_port}")
    print()

    # TSPL font reference:
    # Font "1" = 8x12 dots (smallest)
    # Font "2" = 12x20 dots
    # Font "3" = 16x24 dots
    # Font "4" = 24x32 dots
    # Font "5" = 32x48 dots (largest bitmap)
    # Font "6" = 14x19 dots OCR-B
    # Font "7" = 21x27 dots OCR-B
    # Font "8" = 14x25 dots OCR-A
    # Font "TSS24.BF2" = Monotype CG Triumvirate Scalable (TrueType)
    # Font "ROMAN.TTF" = Roman (TrueType) - if available

    tspl_commands = []

    # Set label size
    tspl_commands.append(f"SIZE {TSC_LABEL_WIDTH_MM:.1f} mm, {TSC_LABEL_HEIGHT_MM:.1f} mm")
    tspl_commands.append("GAP 2 mm, 2 mm")
    tspl_commands.append("DIRECTION 1,0")
    tspl_commands.append("REFERENCE 0,0")
    tspl_commands.append("CLS")
    tspl_commands.append("DENSITY 10")
    tspl_commands.append("SPEED 3")

    # Print title
    tspl_commands.append('TEXT 20,10,"3",0,1,1,"FONT SAMPLES"')
    tspl_commands.append('BAR 20,40,580,2')

    # Y position tracker
    y = 50

    # Test bitmap fonts 1-8 with normal size (1x1 scale)
    fonts_info = [
        ("1", "Font 1 (8x12) - Smallest"),
        ("2", "Font 2 (12x20) - Small"),
        ("3", "Font 3 (16x24) - Medium"),
        ("4", "Font 4 (24x32) - Large"),
        ("5", "Font 5 (32x48) - Largest"),
        ("6", "Font 6 (OCR-B)"),
        ("7", "Font 7 (OCR-B Large)"),
        ("8", "Font 8 (OCR-A)"),
    ]

    for font, description in fonts_info:
        # Label on left, sample text on right
        tspl_commands.append(f'TEXT 20,{y},"1",0,1,1,"{description}"')
        tspl_commands.append(f'TEXT 280,{y},"{font}",0,1,1,"SUNDIAL SC-20GL"')
        y += 25

    tspl_commands.append("PRINT 1,1")

    # Join all commands
    tspl = '\r\n'.join(tspl_commands) + '\r\n'

    print("Sending font samples to printer...")
    print()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((printer_ip, printer_port))

        sock.sendall(tspl.encode('utf-8'))
        sock.close()

        print("✅ Font sample label sent to printer!")
        print()
        print("The label shows all available fonts.")
        print("Each line shows the font number and a sample using that font.")
        print()
        print("Current label uses:")
        print("  - Font 3 for 'SUNDIAL AUDIO'")
        print("  - Font 2 for series, length, SKU")
        print("  - Font 1 for connector details")
        print()
        return True

    except (socket.timeout, socket.error, OSError) as e:
        print(f"❌ Error: {e}")
        print()
        print("Troubleshooting:")
        print(f"  1. Check printer power")
        print(f"  2. Verify connection: ping {printer_ip}")
        return False


def print_font_size_samples(printer_ip, printer_port):
    """Print label showing font scaling options"""

    print()
    print("=" * 70)
    print("Font Scaling Test")
    print("=" * 70)
    print()

    # TSPL TEXT command: TEXT x,y,"font",rotation,x_scale,y_scale,"content"
    # x_scale and y_scale can be 1-10 (or higher on some models)

    tspl_commands = []

    tspl_commands.append(f"SIZE {TSC_LABEL_WIDTH_MM:.1f} mm, {TSC_LABEL_HEIGHT_MM:.1f} mm")
    tspl_commands.append("GAP 2 mm, 2 mm")
    tspl_commands.append("DIRECTION 1,0")
    tspl_commands.append("REFERENCE 0,0")
    tspl_commands.append("CLS")
    tspl_commands.append("DENSITY 10")
    tspl_commands.append("SPEED 3")

    # Title
    tspl_commands.append('TEXT 20,10,"3",0,1,1,"FONT SCALING"')
    tspl_commands.append('BAR 20,35,580,2')

    # Show Font 2 at different scales
    y = 45
    scales = [
        (1, 1, "1x1 (normal)"),
        (1, 2, "1x2 (tall)"),
        (2, 1, "2x1 (wide)"),
        (2, 2, "2x2 (large)"),
    ]

    for x_scale, y_scale, label in scales:
        tspl_commands.append(f'TEXT 20,{y},"1",0,1,1,"{label}:"')
        tspl_commands.append(f'TEXT 150,{y},"2",0,{x_scale},{y_scale},"SUNDIAL"')
        y += 35 if max(x_scale, y_scale) > 1 else 25

    tspl_commands.append("PRINT 1,1")

    tspl = '\r\n'.join(tspl_commands) + '\r\n'

    print("Sending font scaling samples to printer...")
    print()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((printer_ip, printer_port))

        sock.sendall(tspl.encode('utf-8'))
        sock.close()

        print("✅ Font scaling sample label sent to printer!")
        print()
        print("This label shows Font 2 at different scales:")
        print("  - 1x1 = normal size")
        print("  - 1x2 = stretched vertically (tall)")
        print("  - 2x1 = stretched horizontally (wide)")
        print("  - 2x2 = doubled in both directions")
        print()
        return True

    except (socket.timeout, socket.error, OSError) as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Main function"""

    print("This script will print two test labels:")
    print("  1. All available fonts")
    print("  2. Font scaling examples")
    print()

    response = input("Print font test labels? (y/n): ").strip().lower()
    if response != 'y':
        print("Cancelled")
        return 0

    # Print font samples
    if not print_font_samples(TSC_PRINTER_IP, TSC_PRINTER_PORT):
        return 1

    # Wait a moment
    import time
    time.sleep(1)

    # Print scaling samples
    if not print_font_size_samples(TSC_PRINTER_IP, TSC_PRINTER_PORT):
        return 1

    print()
    print("=" * 70)
    print("Test Complete!")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Look at the printed labels")
    print("  2. Choose which fonts you like best")
    print("  3. Let me know which fonts to use for each element:")
    print("     - Brand (SUNDIAL AUDIO)")
    print("     - Series name")
    print("     - Length and color")
    print("     - SKU")
    print("     - Connector details")
    print()
    print("Example: 'Use font 4 for brand, font 3 for series, font 2 for SKU'")
    print()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
