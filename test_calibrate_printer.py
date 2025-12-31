#!/usr/bin/env python3
"""
Calibrate the TSC TE210 printer for proper label detection

This script sends calibration commands to help the printer detect
label gaps correctly, which fixes top margin issues.

Usage:
    python test_calibrate_printer.py
"""

import sys
import os
import socket

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT


def calibrate_printer(printer_ip, printer_port):
    """Send calibration command to printer"""

    print("=" * 60)
    print("TSC TE210 Printer Calibration")
    print("=" * 60)
    print()
    print(f"Printer: {printer_ip}:{printer_port}")
    print()

    # TSPL calibration commands
    calibration_commands = [
        "SIZE 76.2 mm, 25.4 mm",  # Set label size
        "GAP 3 mm, 0 mm",          # Set gap size
        "DIRECTION 1,0",           # Normal direction
        "REFERENCE 0,0",           # Reference point
        "CLS",                     # Clear buffer
        "",                        # Blank line
        "~!T",                     # Get printer status (optional)
        ""
    ]

    tspl = '\r\n'.join(calibration_commands)

    print("Sending calibration commands...")
    print("-" * 60)
    print(tspl)
    print("-" * 60)
    print()

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((printer_ip, printer_port))

        print(f"✅ Connected to printer")

        # Send commands
        sock.sendall(tspl.encode('utf-8'))

        print(f"✅ Calibration commands sent")
        print()
        print("The printer should now detect label gaps correctly.")
        print("Try printing test labels again.")

        sock.close()
        return True

    except (socket.timeout, socket.error, OSError) as e:
        print(f"❌ Error: {e}")
        print()
        print("Troubleshooting:")
        print(f"  1. Check printer power")
        print(f"  2. Verify connection: ping {printer_ip}")
        print(f"  3. Check printer network settings")
        return False


if __name__ == "__main__":
    try:
        success = calibrate_printer(TSC_PRINTER_IP, TSC_PRINTER_PORT)
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
