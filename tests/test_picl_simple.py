#!/usr/bin/env python3
"""
Simple PICL print job generation test
"""

import sys
import os
import json
import base64
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from greenlight.hardware.label_printer import BradyM511Printer

def test_picl_structure():
    """Test and display PICL structure"""
    print("🧪 Brady M511 PICL Print Job Analysis")
    print("=" * 50)
    
    printer = BradyM511Printer()
    picl_data = printer._create_picl_print_job("HELLO")
    
    print(f"📏 Total PICL packet: {len(picl_data)} bytes")
    
    # Decode PICL structure
    picl_header = picl_data[:16]
    json_length = int.from_bytes(picl_data[16:20], byteorder='little')
    json_payload = picl_data[20:20+json_length].decode('utf-8')
    
    print(f"🔍 PICL header: {' '.join(f'{b:02x}' for b in picl_header)}")
    print(f"📋 JSON length: {json_length} bytes")
    print(f"📄 JSON structure:")
    
    # Pretty print the JSON
    json_obj = json.loads(json_payload)
    print(json.dumps(json_obj, indent=2, separators=(',', ': '))[:200] + "...")
    
    # Decode the compressed data
    b64_data = json_obj["PrintJob"]["Data"]
    compressed_data = base64.b64decode(b64_data)
    raw_print_job = zlib.decompress(compressed_data)
    
    print(f"\n📊 Data breakdown:")
    print(f"   🗜️  Compressed bitmap: {len(compressed_data)} bytes")
    print(f"   📄 Raw print job: {len(raw_print_job)} bytes")
    print(f"   🆔 Job ID: {json_obj['PrintJob']['JobId']}")
    
    print(f"\n🔍 Raw print job preview (first 50 bytes):")
    print(f"   {' '.join(f'{b:02x}' for b in raw_print_job[:50])}")
    
    print("\n✅ PICL JSON packaging complete and verified!")

if __name__ == "__main__":
    test_picl_structure()