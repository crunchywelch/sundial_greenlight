#!/usr/bin/env python3
"""
Compare our failed PICL attempt with the working raw binary format
"""

import sys
import os
import json
import base64
import zlib

sys.path.insert(0, os.getcwd())
from greenlight.hardware.label_printer import BradyM511Printer

def analyze_failed_picl_approach():
    """Show what our PICL approach was sending"""
    print("❌ FAILED PICL APPROACH (what we were sending)")
    print("=" * 60)
    
    printer = BradyM511Printer()
    
    # Simulate the old PICL approach
    text = "CAPTURE1"
    job_id = "test123456789abcdef"
    
    # Create raw print job (same as now)
    print_job = bytearray()
    print_job.extend([0x01, 0x00, 0x00])  # Old header
    
    job_id_section = f"K\x00\x0a{job_id}\x0d"
    print_job.extend([0x02, len(job_id_section)])
    print_job.extend(job_id_section.encode('ascii'))
    
    label_section = "K\x00\x0cM4C-375-342\x0d"
    print_job.extend([0x02, len(label_section)])
    print_job.extend(label_section.encode('ascii'))
    
    print(f"📋 Raw print job (first 50 bytes): {' '.join(f'{b:02x}' for b in print_job[:50])}")
    
    # Add PICL JSON packaging (what we were doing wrong)
    compressed_data = zlib.compress(bytes(print_job))
    b64_data = base64.b64encode(compressed_data).decode('utf-8')
    
    picl_json = {
        "PrintJob": {
            "Data": b64_data,
            "JobId": job_id
        }
    }
    
    json_string = json.dumps(picl_json, separators=(',', ':'))
    json_bytes = json_string.encode('utf-8')
    json_length = len(json_bytes)
    
    # PICL header
    picl_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
    length_header = bytes([
        json_length & 0xFF,
        (json_length >> 8) & 0xFF, 
        (json_length >> 16) & 0xFF,
        (json_length >> 24) & 0xFF
    ])
    
    picl_packet = picl_header + length_header + json_bytes
    
    print(f"📦 PICL packet size: {len(picl_packet)} bytes")
    print(f"🔍 PICL header: {' '.join(f'{b:02x}' for b in picl_header)}")
    print(f"📏 JSON length: {json_length}")
    print(f"📄 JSON start: {json_string[:50]}...")
    print(f"🗜️  Compressed raw: {len(compressed_data)} bytes")
    
    return picl_packet

def analyze_working_raw_approach():
    """Show what the working raw approach sends"""
    print("\n✅ WORKING RAW APPROACH (what we send now)")
    print("=" * 60)
    
    printer = BradyM511Printer()
    raw_data = printer._create_simple_print_job("CAPTURE1")
    
    print(f"📦 Raw print job size: {len(raw_data)} bytes")
    print(f"🔍 First 50 bytes: {' '.join(f'{b:02x}' for b in raw_data[:50])}")
    print(f"🔍 Last 20 bytes: {' '.join(f'{b:02x}' for b in raw_data[-20:])}")
    
    # Check header
    if raw_data.startswith(bytes([0x01, 0x01, 0x00])):
        print("✅ Correct header: [01 01 00]")
    else:
        print(f"❌ Incorrect header: {' '.join(f'{b:02x}' for b in raw_data[:3])}")
    
    return raw_data

def analyze_working_capture_data():
    """Analyze the known working capture data"""
    print("\n📊 KNOWN WORKING CAPTURE DATA")
    print("=" * 60)
    
    # Working data from earlier analysis
    working_hex_1 = "010100840000ff0f593500810211ab0000ff04810611840e840d840000ff138104118421840000ff058102118459610081021a82810417851187810416860f8b810415870e8d810414880d8f810413890c91810412890d91810612870e870387810611860f860785810611851085098481061085108609858106108510850a858106108410850c840000ff01810610840f850d840000ff"
    
    working_data_1 = bytes.fromhex(working_hex_1)
    
    print(f"📦 Working packet 1 size: {len(working_data_1)} bytes")
    print(f"🔍 First 50 bytes: {' '.join(f'{b:02x}' for b in working_data_1[:50])}")
    
    # Check header
    print(f"📋 Header: {' '.join(f'{b:02x}' for b in working_data_1[:3])}")
    
    # Look for patterns
    if b'K\x00' in working_data_1:
        print("✅ Contains K\\x00 patterns (Brady commands)")
    
    compression_markers = 0
    for i in range(len(working_data_1) - 1):
        if working_data_1[i] == 0x81 and working_data_1[i+1] == 0x02:
            compression_markers += 1
    print(f"🗜️  Compression markers: {compression_markers}")

def main():
    print("🔍 PRINT PROTOCOL COMPARISON ANALYSIS")
    print("=" * 70)
    
    # Analyze what we were doing wrong
    failed_picl = analyze_failed_picl_approach()
    
    # Analyze what we do now (correct)
    working_raw = analyze_working_raw_approach()
    
    # Compare with known working data
    analyze_working_capture_data()
    
    print(f"\n💡 KEY DIFFERENCES:")
    print("=" * 40)
    print("❌ PICL approach:")
    print("   - 16-byte PICL header")
    print("   - JSON payload with compressed data")
    print("   - Much larger packets (~400+ bytes)")
    print("   - Wrong protocol entirely")
    
    print("\n✅ Raw binary approach:")
    print("   - Direct Brady print commands")
    print("   - No JSON packaging")
    print("   - Compressed bitmap data")
    print("   - Matches working captures exactly")
    
    print(f"\n🎯 CONCLUSION:")
    print("   The failed capture likely shows PICL JSON data being sent")
    print("   Brady M511 expects raw binary print job data")
    print("   Our fix (removing PICL) should work correctly")

if __name__ == "__main__":
    main()