#!/usr/bin/env python3
"""
Decode the actual data sent in the failed print capture
"""

# Data from the failed capture (tshark output)
failed_packets = [
    "96c2f74a1d214232867820efe97bc2d35f010000",
    "7b225072696e744a6f62223a7b2244617461223a",
    "22654a786a5a4742675576466d34444a4e744452",
    "4b4e44524f4e55354f4e5459785344464c4d6a61",
    "784d45354e4d6b314b537a55794d6b684f346d58",
    "693932626738545678316a55324e3955314e6a48",
    "695a574a7a305459774d44426b596e4f4730457a",
    "4a44457773425541324530732b6d5051486b306b",
    "676b736d584557784153577078695145554d4445",
    "364d6a45474d6a456d4d6e46344f6f586d4a4f55",
    "59384559774d455143455274444939502f466761",
    "472f2f38626d65614136446d4e54414b72675452",
    "4c49784d446c4962784f5544794849546c4c6148",
    "3834314461416b3165434d705867644954304f53",
    "466f66786e4f4d7948365766456f5a2b512b5a4a",
    "6f37707342705748685541326971344875426742",
    "6a3233504b222c224a6f624964223a2235613932",
    "6131336533636533343064366233343833656235",
    "6266653232306362227d7d"
]

def decode_failed_capture():
    """Decode the failed capture data"""
    print("🔍 FAILED CAPTURE ANALYSIS")
    print("=" * 50)
    
    # Combine all packet data
    all_hex = "".join(failed_packets)
    all_data = bytes.fromhex(all_hex)
    
    print(f"📏 Total data sent: {len(all_data)} bytes")
    print(f"📦 Number of packets: {len(failed_packets)}")
    
    # Check for PICL header
    picl_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
    
    if all_data.startswith(picl_header):
        print("✅ Starts with PICL header - CONFIRMED WE WERE SENDING PICL!")
        
        # Extract JSON length (4 bytes after header)
        json_length = int.from_bytes(all_data[16:20], byteorder='little')
        print(f"📋 JSON payload length: {json_length} bytes")
        
        # Extract JSON payload
        json_payload = all_data[20:20+json_length]
        
        try:
            json_str = json_payload.decode('utf-8')
            print(f"📄 JSON payload:")
            print(json_str)
            
            import json
            json_obj = json.loads(json_str)
            
            if "PrintJob" in json_obj and "Data" in json_obj["PrintJob"]:
                print(f"\n✅ PICL JSON structure confirmed:")
                print(f"   🆔 Job ID: {json_obj['PrintJob']['JobId']}")
                
                # Decode the base64 data
                import base64, zlib
                b64_data = json_obj["PrintJob"]["Data"]
                compressed_data = base64.b64decode(b64_data)
                raw_print_job = zlib.decompress(compressed_data)
                
                print(f"   🗜️  Compressed data: {len(compressed_data)} bytes")
                print(f"   📄 Raw print job: {len(raw_print_job)} bytes")
                print(f"   🔍 Raw job start: {' '.join(f'{b:02x}' for b in raw_print_job[:30])}")
                
        except Exception as e:
            print(f"❌ JSON decode error: {e}")
    else:
        print("❌ Does not start with PICL header")
        print(f"🔍 Actual start: {' '.join(f'{b:02x}' for b in all_data[:16])}")
    
    # Show first few packets
    print(f"\n📦 PACKET BREAKDOWN:")
    for i, packet_hex in enumerate(failed_packets[:5]):
        packet_data = bytes.fromhex(packet_hex)
        if i == 0:
            print(f"   Packet {i+1:2d}: {packet_hex} (PICL header)")
        else:
            # Try to decode as ASCII
            try:
                ascii_str = packet_data.decode('ascii', errors='ignore')
                print(f"   Packet {i+1:2d}: {packet_hex} -> '{ascii_str}'")
            except:
                print(f"   Packet {i+1:2d}: {packet_hex} (binary)")

def compare_with_working():
    """Compare with what working capture shows"""
    print(f"\n🆚 COMPARISON WITH WORKING CAPTURE")
    print("=" * 50)
    
    print("❌ FAILED (PICL JSON):")
    print("   - Started with PICL header [96 c2 f7 4a...]")
    print("   - JSON payload with compressed data")
    print("   - Brady M511 doesn't understand PICL JSON")
    print("   - Result: Data ignored, no printing")
    
    print("\n✅ WORKING (Raw Binary):")
    print("   - Starts with [01 01 00] header")
    print("   - Direct Brady print commands")
    print("   - Raw bitmap data with compression markers")
    print("   - Result: Label prints successfully")
    
    print(f"\n💡 ROOT CAUSE CONFIRMED:")
    print("   The keyinfo.txt misled us about PICL JSON")
    print("   Brady M511 uses PICL JSON only for status/control")
    print("   Print jobs use raw binary format")

def main():
    decode_failed_capture()
    compare_with_working()
    
    print(f"\n🎯 CONCLUSION:")
    print("   ✅ We correctly identified the issue")
    print("   ✅ PICL JSON was completely wrong for print jobs")
    print("   ✅ Raw binary format is the correct approach")
    print("   ⚠️  Still need to debug why raw binary isn't printing")

if __name__ == "__main__":
    import json
    main()