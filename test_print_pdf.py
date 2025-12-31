#!/usr/bin/env python3
"""
Test script to print SC-20GL.pdf to the TSC TE210 printer

This script sends the PDF file directly to the printer via raw socket connection.

Usage:
    python test_print_pdf.py [pdf_file]

Arguments:
    pdf_file    Path to PDF file (default: SC-20GL.pdf)

The script will:
1. Read the PDF file
2. Send it to the printer at 192.168.0.52:9100
3. Report success or failure
"""

import sys
import os
import socket
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from greenlight.config import TSC_PRINTER_IP, TSC_PRINTER_PORT


def print_pdf_raw(pdf_path, printer_ip, printer_port):
    """
    Print PDF file by sending it directly to printer via raw socket

    Args:
        pdf_path: Path to PDF file
        printer_ip: Printer IP address
        printer_port: Printer port (usually 9100 for raw printing)

    Returns:
        True if successful, False otherwise
    """
    print(f"Reading PDF file: {pdf_path}")

    # Check if file exists
    if not os.path.exists(pdf_path):
        print(f"❌ Error: File not found: {pdf_path}")
        return False

    # Read PDF file
    try:
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()

        file_size = len(pdf_data)
        print(f"✅ Read {file_size:,} bytes from PDF")
    except Exception as e:
        print(f"❌ Error reading PDF file: {e}")
        return False

    # Connect to printer
    print(f"\nConnecting to printer at {printer_ip}:{printer_port}...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)
        sock.connect((printer_ip, printer_port))
        print(f"✅ Connected to printer")
    except (socket.timeout, socket.error, OSError) as e:
        print(f"❌ Error connecting to printer: {e}")
        print(f"\nTroubleshooting:")
        print(f"  1. Check if printer is powered on")
        print(f"  2. Verify network connection: ping {printer_ip}")
        print(f"  3. Check if printer IP is correct")
        print(f"  4. Ensure printer is on the same network")
        return False

    # Send PDF data to printer
    print(f"\nSending PDF data to printer...")

    try:
        # Send the PDF data
        bytes_sent = 0
        chunk_size = 4096

        while bytes_sent < file_size:
            chunk = pdf_data[bytes_sent:bytes_sent + chunk_size]
            sock.sendall(chunk)
            bytes_sent += len(chunk)

            # Show progress for larger files
            if file_size > 10000:
                progress = (bytes_sent / file_size) * 100
                print(f"  Progress: {progress:.1f}% ({bytes_sent:,} / {file_size:,} bytes)", end='\r')

        if file_size > 10000:
            print()  # New line after progress

        print(f"✅ Sent {bytes_sent:,} bytes to printer")

        # Give printer time to process
        print(f"\nWaiting for printer to process...")
        time.sleep(2)

    except (socket.timeout, socket.error, OSError) as e:
        print(f"\n❌ Error sending data to printer: {e}")
        sock.close()
        return False

    # Close connection
    sock.close()
    print(f"✅ Connection closed")

    return True


def print_pdf_lpr(pdf_path, printer_ip):
    """
    Alternative method: Print PDF using lpr/lp system commands

    This requires CUPS to be installed and printer to be configured in CUPS.

    Args:
        pdf_path: Path to PDF file
        printer_ip: Printer IP address

    Returns:
        True if successful, False otherwise
    """
    import subprocess

    print(f"\nAttempting to print using system lpr command...")

    # Try to find the printer in CUPS
    try:
        # Check if lpr is available
        result = subprocess.run(['which', 'lpr'], capture_output=True, text=True)
        if result.returncode != 0:
            print("❌ lpr command not found (CUPS not installed)")
            return False

        # Try to print using raw queue
        # This assumes the printer is set up in CUPS with the IP address
        cmd = ['lpr', '-H', f'{printer_ip}:9100', '-o', 'raw', pdf_path]
        print(f"Running: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            print(f"✅ Print job sent via lpr")
            return True
        else:
            print(f"❌ lpr failed: {result.stderr}")
            return False

    except subprocess.TimeoutExpired:
        print(f"❌ Print command timed out")
        return False
    except Exception as e:
        print(f"❌ Error using lpr: {e}")
        return False


def main():
    """Main function"""

    # Get PDF file path from command line or use default
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
    else:
        pdf_path = "SC-20GL.pdf"

    print("=" * 70)
    print("TSC TE210 - PDF Printing Test")
    print("=" * 70)
    print()
    print(f"PDF File: {pdf_path}")
    print(f"Printer:  {TSC_PRINTER_IP}:{TSC_PRINTER_PORT}")
    print()

    # Convert to absolute path
    if not os.path.isabs(pdf_path):
        pdf_path = os.path.join(os.getcwd(), pdf_path)

    # Check if file exists
    if not os.path.exists(pdf_path):
        print(f"❌ Error: PDF file not found: {pdf_path}")
        print()
        print("Usage: python test_print_pdf.py [pdf_file]")
        print("Example: python test_print_pdf.py SC-20GL.pdf")
        return 1

    # Show file info
    file_size = os.path.getsize(pdf_path)
    print(f"File size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")
    print()

    # Ask for confirmation
    print("This will send the PDF to the printer.")
    response = input("Continue? (y/n): ").strip().lower()

    if response != 'y':
        print("Cancelled")
        return 0

    print()
    print("-" * 70)
    print("METHOD 1: Raw Socket Printing")
    print("-" * 70)

    # Try raw socket method first
    success = print_pdf_raw(pdf_path, TSC_PRINTER_IP, TSC_PRINTER_PORT)

    if success:
        print()
        print("=" * 70)
        print("✅ PDF sent to printer successfully!")
        print("=" * 70)
        print()
        print("Note: Check the printer to see if the label printed correctly.")
        print("Some label printers may not support PDF printing directly.")
        print("If nothing prints, the printer may require TSPL or image format instead.")
        return 0
    else:
        print()
        print("=" * 70)
        print("Raw socket printing failed")
        print("=" * 70)

        # Try alternative method
        print()
        print("-" * 70)
        print("METHOD 2: System lpr/lp Command")
        print("-" * 70)

        success = print_pdf_lpr(pdf_path, TSC_PRINTER_IP)

        if success:
            print()
            print("=" * 70)
            print("✅ PDF sent via lpr successfully!")
            print("=" * 70)
            return 0
        else:
            print()
            print("=" * 70)
            print("❌ Both printing methods failed")
            print("=" * 70)
            print()
            print("Troubleshooting:")
            print("  1. Verify printer is on and connected: ping", TSC_PRINTER_IP)
            print("  2. Check if printer supports PDF printing")
            print("  3. Try printing from Windows/Mac with Adobe Acrobat")
            print("  4. The printer may only support TSPL commands")
            print()
            print("Alternative: Use the TSPL-based label printing:")
            print("  python test_label_printer.py")
            return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
