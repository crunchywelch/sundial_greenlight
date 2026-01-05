#!/usr/bin/env python3
"""
Upload a bitmap file to the TSC label printer.

Usage:
    python util/upload_bitmap.py <bitmap_file> [printer_ip]

Example:
    python util/upload_bitmap.py wire_mono.bmp
    python util/upload_bitmap.py wire_mono.bmp 192.168.0.52
"""

import socket
import sys
import os

DEFAULT_PRINTER_IP = "192.168.0.52"
PRINTER_PORT = 9100


def upload_bitmap(filepath: str, printer_ip: str) -> bool:
    """Upload a BMP file to the TSC printer's memory."""

    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return False

    # Get just the filename for the printer
    filename = os.path.basename(filepath).upper()

    # Read the bitmap data
    with open(filepath, 'rb') as f:
        data = f.read()

    # Verify it's a BMP
    if data[:2] != b'BM':
        print(f"Error: {filepath} is not a valid BMP file")
        return False

    print(f"Uploading {filename} ({len(data)} bytes) to {printer_ip}...")

    # Build the DOWNLOAD command
    cmd = f'DOWNLOAD "{filename}",{len(data)}\r\n'.encode() + data

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10.0)
        s.connect((printer_ip, PRINTER_PORT))
        s.sendall(cmd)
        s.close()
        print(f"Uploaded {filename} successfully")
        return True
    except (socket.timeout, socket.error, OSError) as e:
        print(f"Error uploading to printer: {e}")
        return False


def list_printer_files(printer_ip: str):
    """List files stored on the printer."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((printer_ip, PRINTER_PORT))
        s.sendall(b'FILES\r\n')
        s.settimeout(2.0)
        try:
            response = s.recv(4096)
            print("Files on printer:")
            print(response.decode('utf-8', errors='ignore'))
        except socket.timeout:
            print("No response (printer may not support FILES command)")
        s.close()
    except (socket.error, OSError) as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if sys.argv[1] == "--list":
        printer_ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PRINTER_IP
        list_printer_files(printer_ip)
    else:
        filepath = sys.argv[1]
        printer_ip = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_PRINTER_IP
        success = upload_bitmap(filepath, printer_ip)
        sys.exit(0 if success else 1)
