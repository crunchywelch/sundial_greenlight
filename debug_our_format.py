#!/usr/bin/env python3
"""
Debug our current raw binary format to understand what we're actually sending
"""

import sys
import os

sys.path.insert(0, os.getcwd())
from greenlight.hardware.label_printer import BradyM511Printer

def analyze_our_print_job():
    """Analyze what our current implementation generates"""
    print("🔍 ANALYZING OUR CURRENT RAW BINARY FORMAT")
    print("=" * 60)
    
    printer = BradyM511Printer()
    text = "TEST123"
    
    print(f"📝 Generating print job for: '{text}'")
    raw_data = printer._create_simple_print_job(text)
    
    print(f"📦 Total size: {len(raw_data)} bytes")
    print()
    
    # Analyze structure
    print("🔍 STRUCTURE ANALYSIS:")
    print("=" * 40)
    
    # Header
    header = raw_data[:3]
    print(f"📋 Header: {' '.join(f'{b:02x}' for b in header)}")
    
    # Parse sections
    pos = 3
    section_num = 1
    
    while pos < len(raw_data) and section_num <= 20:  # Limit to prevent infinite loop
        if pos + 1 >= len(raw_data):
            break
            
        section_type = raw_data[pos]
        if section_type == 0x02:  # Text section
            section_len = raw_data[pos + 1]
            section_data = raw_data[pos + 2:pos + 2 + section_len]
            
            # Try to decode as ASCII
            try:
                text_content = section_data.decode('ascii', errors='ignore')
                print(f"📄 Section {section_num:2d} (type 02): len={section_len:2d}, '{text_content}'")
            except:
                hex_content = ' '.join(f'{b:02x}' for b in section_data)
                print(f"📄 Section {section_num:2d} (type 02): len={section_len:2d}, {hex_content}")
            
            pos += 2 + section_len
            section_num += 1
            
        elif section_type in [0x58, 0x59]:  # Coordinate sections
            coord_value = int.from_bytes(raw_data[pos + 1:pos + 3], 'little')
            print(f"📍 Section {section_num:2d} (type {section_type:02x}): coordinate={coord_value}")
            pos += 3
            section_num += 1
            
        else:
            # Unknown section or bitmap data
            remaining = len(raw_data) - pos
            if remaining > 50:
                print(f"🗜️  Section {section_num:2d} (type {section_type:02x}): bitmap data ({remaining} bytes)")
                print(f"     First 30 bytes: {' '.join(f'{b:02x}' for b in raw_data[pos:pos+30])}")
                print(f"     Last 20 bytes:  {' '.join(f'{b:02x}' for b in raw_data[-20:])}")
            else:
                print(f"📄 Section {section_num:2d} (type {section_type:02x}): {' '.join(f'{b:02x}' for b in raw_data[pos:pos+min(20, remaining)])}")
            break
    
    print()
    print("🔍 COMPRESSION ANALYSIS:")
    print("=" * 40)
    
    # Count compression markers
    compression_markers = 0
    for i in range(len(raw_data) - 1):
        if raw_data[i] == 0x81 and raw_data[i + 1] == 0x02:
            compression_markers += 1
    
    print(f"🗜️  Total compression markers (81 02): {compression_markers}")
    
    # Look for specific Brady patterns
    patterns = {
        b'K\x00\x0a': 'Job ID pattern',
        b'K\x00\x0c': 'Label type pattern', 
        b'M4C-375-342': 'M4C-375-342 label',
        b'D+0001': 'D command',
        b'C+0001': 'C command',
        b'IBUlbl': 'Text format command'
    }
    
    print("🔍 Brady command patterns found:")
    for pattern, description in patterns.items():
        if pattern in raw_data:
            idx = raw_data.find(pattern)
            print(f"   ✅ {description} at byte {idx}")
        else:
            print(f"   ❌ {description} not found")

def compare_sizes():
    """Compare our format size with typical Brady prints"""
    print(f"\n📊 SIZE COMPARISON:")
    print("=" * 40)
    print("Our format:     690 bytes (very large)")
    print("Failed PICL:    371 bytes")  
    print("Expected Brady: ~150-200 bytes typical")
    print()
    print("🤔 POSSIBLE ISSUES:")
    print("1. Our bitmap generation might be too large")
    print("2. We might be including unnecessary commands")
    print("3. The compression algorithm might not be working correctly")
    print("4. We need a successful Brady print capture for comparison")

def main():
    analyze_our_print_job()
    compare_sizes()
    
    print(f"\n🎯 NEXT STEPS:")
    print("1. Get capture of successful Brady print (from Brady Workstation)")
    print("2. Compare our 690-byte format with actual working format")  
    print("3. Identify what's causing our format to be too large")
    print("4. Simplify our format to match working Brady prints")

if __name__ == "__main__":
    main()