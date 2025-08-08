#!/usr/bin/env python3
"""
Test minimal data write to Brady M511 to isolate the offset error
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady

BRADY_MAC = "88:8C:19:00:E2:49"

async def test_minimal_write():
    """Test writing minimal data to isolate the offset issue"""
    print("🧪 Brady M511 Minimal Write Test")
    print("=" * 40)
    
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
                        print(f"✅ Found print job char: {char.uuid}")
                        break
                if print_job_char:
                    break
        
        if not print_job_char:
            print("❌ Print job characteristic not found")
            await disconnect_from_brady(client)
            return False
        
        # Test 1: Try writing 1 byte
        print("\n📝 Test 1: Writing 1 byte...")
        try:
            test_data_1 = bytes([0x01])
            await client.write_gatt_char(print_job_char, test_data_1)
            print("✅ 1 byte write successful")
        except Exception as e:
            print(f"❌ 1 byte write failed: {e}")
        
        # Test 2: Try writing 4 bytes  
        print("\n📝 Test 2: Writing 4 bytes...")
        try:
            test_data_4 = bytes([0x01, 0x02, 0x03, 0x04])
            await client.write_gatt_char(print_job_char, test_data_4)
            print("✅ 4 byte write successful")
        except Exception as e:
            print(f"❌ 4 byte write failed: {e}")
        
        # Test 3: Try writing 20 bytes
        print("\n📝 Test 3: Writing 20 bytes...")
        try:
            test_data_20 = bytes(range(20))
            await client.write_gatt_char(print_job_char, test_data_20)
            print("✅ 20 byte write successful") 
        except Exception as e:
            print(f"❌ 20 byte write failed: {e}")
        
        # Test 4: Try writing PICL header only
        print("\n📝 Test 4: Writing PICL header (16 bytes)...")
        try:
            picl_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
            await client.write_gatt_char(print_job_char, picl_header)
            print("✅ PICL header write successful")
        except Exception as e:
            print(f"❌ PICL header write failed: {e}")
        
        await disconnect_from_brady(client)
        print("\n✅ Test completed")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_minimal_write())