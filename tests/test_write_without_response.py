#!/usr/bin/env python3
"""
Test using write_gatt_char with response=False (write-without-response)
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady

BRADY_MAC = "88:8C:19:00:E2:49"

async def test_write_without_response():
    """Test writing with response=False"""
    print("🧪 Brady M511 Write Without Response Test")
    print("=" * 45)
    
    try:
        print("🔌 Connecting...")
        client, connected = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        if not connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connected")
        
        # Find print job characteristic
        print_job_char = None
        services = client.services
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                for char in service.characteristics:
                    if "7d9d9a4d" in str(char.uuid).lower():
                        print_job_char = char
                        print(f"✅ Found print job char")
                        print(f"   Properties: {list(char.properties)}")
                        break
                if print_job_char:
                    break
        
        if not print_job_char:
            print("❌ Print job characteristic not found")
            await disconnect_from_brady(client)
            return False
        
        # Test 1: Write without response - 1 byte
        print("\n📝 Test 1: Write 1 byte (no response)...")
        try:
            test_data = bytes([0x01])
            await client.write_gatt_char(print_job_char, test_data, response=False)
            print("✅ 1 byte write (no response) successful")
        except Exception as e:
            print(f"❌ 1 byte write (no response) failed: {e}")
        
        # Test 2: Write without response - 20 bytes  
        print("\n📝 Test 2: Write 20 bytes (no response)...")
        try:
            test_data = bytes(range(20))
            await client.write_gatt_char(print_job_char, test_data, response=False)
            print("✅ 20 byte write (no response) successful")
        except Exception as e:
            print(f"❌ 20 byte write (no response) failed: {e}")
        
        # Test 3: Write with smaller chunks
        print("\n📝 Test 3: Write PICL header in 4-byte chunks (no response)...")
        try:
            picl_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
            
            for i in range(0, len(picl_header), 4):
                chunk = picl_header[i:i+4]
                await client.write_gatt_char(print_job_char, chunk, response=False)
                await asyncio.sleep(0.1)  # Small delay between chunks
                print(f"   Chunk {i//4 + 1}: {len(chunk)} bytes")
            
            print("✅ PICL header chunked write successful")
        except Exception as e:
            print(f"❌ PICL header chunked write failed: {e}")
        
        await disconnect_from_brady(client)
        print("\n✅ Test completed")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_write_without_response())