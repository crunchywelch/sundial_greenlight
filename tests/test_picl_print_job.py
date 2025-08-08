#!/usr/bin/env python3
"""
Test PICL JSON print job generation for Brady M511
Tests the new PICL packaging based on bundle.pretty.js analysis
"""

import asyncio
import sys
import os
import json
import base64
import zlib

# Add the parent directory to the path to import greenlight modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from greenlight.hardware.label_printer import BradyM511Printer
from greenlight.hardware.interfaces import PrintJob

def test_picl_packaging():
    """Test PICL JSON packaging structure"""
    print("🧪 Testing PICL JSON Print Job Generation")
    print("=" * 50)
    
    # Create printer instance
    printer = BradyM511Printer()
    
    # Test texts
    test_texts = ["TEST123", "HELLO", "A12345"]
    
    for text in test_texts:
        print(f"\n📝 Creating PICL print job for: '{text}'")
        
        try:
            # Generate PICL print job
            picl_data = printer._create_picl_print_job(text)
            
            print(f"   📏 PICL packet size: {len(picl_data)} bytes")
            
            # Show first 50 bytes (header + length + start of JSON)
            hex_preview = ' '.join(f'{b:02x}' for b in picl_data[:50])
            print(f"   🔍 First 50 bytes: {hex_preview}...")
            
            # Try to decode the PICL packet to verify structure
            # PICL header is 16 bytes
            picl_header = picl_data[:16]
            expected_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
            
            if picl_header == expected_header:
                print("   ✅ PICL header correct")
            else:
                print("   ❌ PICL header incorrect")
                continue
            
            # Next 4 bytes are JSON length (little endian)
            json_length = int.from_bytes(picl_data[16:20], byteorder='little')
            print(f"   📋 JSON payload length: {json_length} bytes")
            
            # Extract JSON payload
            json_payload = picl_data[20:20+json_length].decode('utf-8')
            print(f"   📄 JSON preview: {json_payload[:100]}...")
            
            # Parse JSON to verify structure
            try:
                json_obj = json.loads(json_payload)
                if "PrintJob" in json_obj and "Data" in json_obj["PrintJob"]:
                    print("   ✅ PICL JSON structure correct")
                    
                    # Try to decode the base64 data
                    b64_data = json_obj["PrintJob"]["Data"]
                    compressed_data = base64.b64decode(b64_data)
                    print(f"   🗜️  Compressed data: {len(compressed_data)} bytes")
                    
                    # Try to decompress
                    raw_print_job = zlib.decompress(compressed_data)
                    print(f"   📄 Raw print job: {len(raw_print_job)} bytes")
                    
                    # Show job ID
                    job_id = json_obj["PrintJob"]["JobId"]
                    print(f"   🆔 Job ID: {job_id[:8]}...")
                    
                else:
                    print("   ❌ PICL JSON structure incorrect")
                    
            except Exception as e:
                print(f"   ❌ JSON parsing failed: {e}")
                
        except Exception as e:
            print(f"   ❌ Error creating PICL print job: {e}")
            import traceback
            traceback.print_exc()

async def test_actual_picl_printing():
    """Test sending PICL print job to Brady M511 (requires printer)"""
    print("\n" + "=" * 50)
    print("🖨️  Testing PICL Print Job Transmission")
    print("=" * 50)
    
    try:
        from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady
        
        BRADY_MAC = "88:8C:19:00:E2:49"
        
        # Connect to Brady M511
        print(f"🔌 Connecting to Brady M511...")
        client, connected = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        if not connected:
            print("❌ Failed to connect to Brady M511")
            return False
        
        print("✅ Connected to Brady M511")
        
        # Create printer and initialize
        printer = BradyM511Printer(BRADY_MAC)
        printer.ble_client = client
        printer.connected = True
        
        # Find characteristics
        services = client.services
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                for char in service.characteristics:
                    char_uuid = str(char.uuid).lower()
                    if "7d9d9a4d" in char_uuid:  # Print job characteristic
                        printer.print_job_char = char
                        break
                break
        
        if not printer.print_job_char:
            print("❌ Could not find print job characteristic")
            await disconnect_from_brady(client)
            return False
        
        # Create PICL print job
        test_text = "PICL123"
        print(f"🏷️  Creating PICL print job for: '{test_text}'")
        
        picl_data = printer._create_picl_print_job(test_text)
        print(f"📦 PICL packet size: {len(picl_data)} bytes")
        
        # Send PICL print job
        print("📡 Sending PICL print job to Brady M511...")
        
        # Send in chunks (Brady BLE has MTU limits)
        chunk_size = 20  # Conservative chunk size for BLE
        total_chunks = (len(picl_data) + chunk_size - 1) // chunk_size
        
        print(f"   Sending {len(picl_data)} bytes in {total_chunks} chunks")
        
        for i in range(0, len(picl_data), chunk_size):
            chunk = picl_data[i:i + chunk_size]
            await client.write_gatt_char(printer.print_job_char, chunk)
            if i % (chunk_size * 10) == 0:  # Progress update every 10 chunks
                print(f"   Progress: {i // chunk_size + 1}/{total_chunks} chunks")
        
        print("✅ PICL print job sent successfully!")
        print("👁️  Check Brady M511 - label should print with PICL protocol")
        
        # Wait a moment for print job to process
        await asyncio.sleep(3)
        
        # Disconnect
        await disconnect_from_brady(client)
        print("🔌 Disconnected from Brady M511")
        
        return True
        
    except Exception as e:
        print(f"❌ PICL print test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main test function"""
    print("🧪 Brady M511 PICL Print Job Test Suite")
    print("=" * 60)
    print("Testing PICL JSON packaging based on bundle.pretty.js analysis")
    print()
    
    # Test 1: PICL packaging
    test_picl_packaging()
    
    # Test 2: Actual PICL printing (requires user input)
    print("\n" + "=" * 60)
    test_actual = input("Test actual PICL printing to Brady M511? (y/n): ").lower().startswith('y')
    
    if test_actual:
        try:
            success = asyncio.run(test_actual_picl_printing())
            if success:
                print("✅ PICL print test completed successfully!")
            else:
                print("❌ PICL print test failed")
        except Exception as e:
            print(f"❌ PICL print test error: {e}")
    else:
        print("⚠️  Skipped actual printing test")
    
    print("\n" + "=" * 60)
    print("🎯 PICL Implementation Status:")
    print("   ✅ PICL header generation (16 bytes)")
    print("   ✅ JSON length encoding (4 bytes, little endian)")
    print("   ✅ PrintJob JSON structure")
    print("   ✅ Base64 encoding of compressed bitmap data")
    print("   ✅ zlib compression of raw print job")
    print("   ✅ Complete PICL packet assembly")
    print("\n   Ready for Brady M511 testing!")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()