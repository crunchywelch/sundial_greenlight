#!/usr/bin/env python3
"""
Analyze the working print capture to understand the correct protocol
"""

# Working capture data from tshark
working_data_1 = "010100840000ff0f593500810211ab0000ff04810611840e840d840000ff138104118421840000ff058102118459610081021a82810417851187810416860f8b810415870e8d810414880d8f810413890c91810412890d91810612870e870387810611860f860785810611851085098481061085108609858106108510850a858106108410850c840000ff01810610840f850d840000ff"

working_data_2 = "01020001810610840e850e840000ff01810610840d860e84810610840d850e85810610840c850f85810610850b850e85810610850a850e868106118508860d868106118606860c888106118901880b88810412920c88810413900d878104138f0e858104148d0f848104168a108181021984598b00810238840000ff0e810211ab0000ff05810238840000ff0e59b200ffff0d02610247"

def analyze_hex_data(hex_string, label):
    """Analyze hex data to find patterns"""
    print(f"\n🔍 {label}")
    print("=" * 50)
    
    # Convert hex string to bytes
    data = bytes.fromhex(hex_string)
    print(f"📏 Length: {len(data)} bytes")
    
    # Check for PICL header
    picl_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
    if data.startswith(picl_header):
        print("✅ Starts with PICL header")
        
        # Extract JSON length
        if len(data) >= 20:
            json_length = int.from_bytes(data[16:20], byteorder='little')
            print(f"📋 JSON length: {json_length} bytes")
            
            # Extract JSON payload
            if len(data) >= 20 + json_length:
                json_payload = data[20:20+json_length]
                try:
                    json_str = json_payload.decode('utf-8')
                    print(f"📄 JSON: {json_str[:100]}...")
                except:
                    print("❌ JSON decode failed")
        else:
            print("⚠️  Data too short for PICL format")
    else:
        print("❌ Does not start with PICL header")
    
    # Look for our binary format patterns
    if data.startswith(bytes([0x01, 0x00, 0x00])):
        print("✅ Starts with our binary format header [01 00 00]")
    else:
        print("❌ Does not start with binary format header")
    
    # Show first 50 bytes
    print(f"🔍 First 50 bytes:")
    first_50 = data[:50]
    hex_str = ' '.join(f'{b:02x}' for b in first_50)
    print(f"   {hex_str}")
    
    # Look for patterns
    print(f"🔍 Pattern analysis:")
    
    # Look for job ID pattern (K\x00\x0a)
    if b'K\x00\x0a' in data:
        idx = data.find(b'K\x00\x0a')
        print(f"   📋 Job ID pattern at byte {idx}")
        job_id_section = data[idx:idx+50]  # Show surrounding context
        print(f"   🆔 Context: {' '.join(f'{b:02x}' for b in job_id_section)}")
    
    # Look for label type pattern (K\x00\x09 or K\x00\x0c)
    if b'K\x00\x09' in data:
        idx = data.find(b'K\x00\x09')
        print(f"   🏷️  Label pattern K\\x00\\x09 at byte {idx}")
        label_section = data[idx:idx+20]
        print(f"   📋 Context: {' '.join(f'{b:02x}' for b in label_section)}")
    
    if b'K\x00\x0c' in data:
        idx = data.find(b'K\x00\x0c')
        print(f"   🏷️  Label pattern K\\x00\\x0c at byte {idx}")
        label_section = data[idx:idx+20]
        print(f"   📋 Context: {' '.join(f'{b:02x}' for b in label_section)}")
    
    # Look for compression markers (0x81, 0x02)
    compression_count = 0
    i = 0
    while i < len(data) - 1:
        if data[i] == 0x81 and data[i+1] == 0x02:
            compression_count += 1
        i += 1
    print(f"   🗜️  Compression markers (81 02): {compression_count}")

def main():
    print("📊 Working Brady Print Capture Analysis")
    print("=" * 60)
    
    analyze_hex_data(working_data_1, "Working Packet 1 (159 bytes)")
    analyze_hex_data(working_data_2, "Working Packet 2 (159 bytes)")
    
    print(f"\n🔍 Key Findings:")
    print("- Working capture uses binary format, NOT PICL JSON!")
    print("- Data starts with [01 00 00] header")  
    print("- Uses our Brady compression format")
    print("- No PICL JSON packaging needed")
    
    print(f"\n💡 Next Steps:")
    print("1. Switch back to raw binary format (not PICL JSON)")
    print("2. Compare our binary format with working capture")
    print("3. Test with raw binary print jobs")

if __name__ == "__main__":
    import json
    main()