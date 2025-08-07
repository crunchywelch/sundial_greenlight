#!/usr/bin/env python3
"""
Simple Brady M511 print test without external dependencies
Uses the exact format observed in Wireshark capture
"""

import asyncio
import logging
import uuid
import struct
import json
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"
PICL_REQUEST_CHAR_UUID = "a61ae408-3273-420c-a9db-0669f4f23b69"
PICL_RESPONSE_CHAR_UUID = "786af345-1b68-c594-c643-e2867da117e3"

async def send_simple_print_job():
    """Send a simple print job using the exact format from Wireshark"""
    
    # Use exact data from Wireshark capture (first packet)
    wireshark_print_data = bytes.fromhex(
        "010000024b000a6637326638626261376339623463343339316437373335663236346164333934643938340d024b00094d34432d3138370d02442b3030303102432b3030303102630002702b3030026f2b3030024f2b303002622b3030024d01024b000c3030383230313738024102510261024942556c626c300d580000590000590600810238840000ff0f810211ab0000ff04810238"
    )
    
    print(f"🧪 Sending Brady M511 print job from Wireshark capture")
    print(f"📦 Data size: {len(wireshark_print_data)} bytes")
    
    client = None
    try:
        # Connect to printer
        print(f"🔌 Connecting to Brady M511...")
        client = BleakClient(BRADY_MAC, timeout=15.0)
        await client.connect()
        
        if not client.is_connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connected to Brady M511")
        
        # Find print job characteristic
        services = client.services
        brady_service = None
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                break
        
        if not brady_service:
            print("❌ Brady service not found")
            return False
        
        print_job_char = None
        for char in brady_service.characteristics:
            if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                print_job_char = char
                break
        
        if not print_job_char:
            print("❌ Print job characteristic not found")
            return False
        
        print("📡 Sending print job data...")
        
        # Send in chunks like the Wireshark capture showed
        chunk_size = 151  # Size of first packet from Wireshark
        total_chunks = (len(wireshark_print_data) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(wireshark_print_data), chunk_size):
            chunk = wireshark_print_data[i:i+chunk_size]
            chunk_num = i // chunk_size + 1
            
            print(f"   📤 Sending chunk {chunk_num}/{total_chunks}: {len(chunk)} bytes")
            await client.write_gatt_char(print_job_char, chunk)
            await asyncio.sleep(0.1)  # Brief pause
        
        print("✅ Print job sent successfully!")
        print("🖨️  Check Brady M511 printer for output")
        
        return True
        
    except Exception as e:
        print(f"❌ Print job failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        if client and client.is_connected:
            print("🔌 Disconnecting...")
            await client.disconnect()

async def send_custom_print_job(text: str):
    """Send a custom print job with modified text"""
    
    print(f"🧪 Creating custom Brady M511 print job for: '{text}'")
    
    # Generate job ID
    job_id = uuid.uuid4().hex
    print(f"🆔 Job ID: {job_id}")
    
    # Build custom print job based on Wireshark structure
    print_job = bytearray()
    
    # Packet header (from Wireshark)
    print_job.extend([0x01, 0x00, 0x00])
    
    # Job ID section
    job_id_section = f"K\x00\x0a{job_id}\x0d"
    print_job.extend([0x02, len(job_id_section)])
    print_job.extend(job_id_section.encode('ascii'))
    
    # Label type
    label_section = "K\x00\x09M4C-187\x0d"
    print_job.extend([0x02, len(label_section)])
    print_job.extend(label_section.encode('ascii'))
    
    # Position commands (from Wireshark)
    commands = ["D+0001", "C+0001", "c\x00", "p+00", "o+00", "O+00", "b+00", "M\x01"]
    for cmd in commands:
        print_job.extend([0x02, len(cmd)])
        print_job.extend(cmd.encode('ascii'))
    
    # Content section - use our custom text
    content_id = text[:8].ljust(8, '0')
    content_section = f"K\x00\x0c{content_id}"
    print_job.extend([0x02, len(content_section)])
    print_job.extend(content_section.encode('ascii'))
    
    # Brady commands
    for cmd in ["A", "Q", "a"]:
        print_job.extend([0x02, len(cmd)])
        print_job.extend(cmd.encode('ascii'))
    
    # Text format
    text_format = "IBUlbl0\x0d"
    print_job.extend([0x02, len(text_format)])
    print_job.extend(text_format.encode('ascii'))
    
    # Simple bitmap section (minimal for now)
    print_job.extend([0x58, 0x00, 0x00])  # X pos
    print_job.extend([0x59, 0x00, 0x00])  # Y pos  
    print_job.extend([0x59, 0x06, 0x00])  # Dimensions
    
    # Simple bitmap data pattern
    bitmap_pattern = bytes([0x81, 0x02, 0x38, 0x84, 0x00, 0x00, 0xff, 0x0f,
                           0x81, 0x02, 0x11, 0xab, 0x00, 0x00, 0xff, 0x04,
                           0x81, 0x02, 0x38])
    print_job.extend(bitmap_pattern)
    
    print(f"📦 Custom print job size: {len(print_job)} bytes")
    
    # Send the job
    client = None
    try:
        print(f"🔌 Connecting to Brady M511...")
        client = BleakClient(BRADY_MAC, timeout=15.0)
        await client.connect()
        
        if not client.is_connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connected")
        
        # Find characteristics
        services = client.services
        brady_service = None
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                break
        
        print_job_char = None
        for char in brady_service.characteristics:
            if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                print_job_char = char
                break
        
        if not print_job_char:
            print("❌ Print job characteristic not found")
            return False
        
        print("📡 Sending custom print job...")
        
        # Send in chunks
        chunk_size = 150
        for i in range(0, len(print_job), chunk_size):
            chunk = print_job[i:i+chunk_size]
            chunk_num = i // chunk_size + 1
            total_chunks = (len(print_job) + chunk_size - 1) // chunk_size
            
            print(f"   📤 Chunk {chunk_num}/{total_chunks}: {len(chunk)} bytes")
            await client.write_gatt_char(print_job_char, chunk)
            await asyncio.sleep(0.1)
        
        print("✅ Custom print job sent!")
        print("🖨️  Check Brady M511 for printed label")
        return True
        
    except Exception as e:
        print(f"❌ Custom print job failed: {e}")
        return False
    finally:
        if client and client.is_connected:
            await client.disconnect()

async def main():
    """Main test function"""
    print("🧪 Brady M511 Simple Print Test")
    print("=" * 50)
    
    # Test 1: Send exact Wireshark data
    print("\n🔬 Test 1: Sending exact Wireshark capture data")
    success1 = await send_simple_print_job()
    
    if success1:
        print("✅ Wireshark replay successful!")
    else:
        print("❌ Wireshark replay failed")
    
    # Wait a moment
    await asyncio.sleep(2)
    
    # Test 2: Send custom print job
    print("\n🔬 Test 2: Sending custom print job")
    custom_text = "HELLO"
    success2 = await send_custom_print_job(custom_text)
    
    if success2:
        print("✅ Custom print job successful!")
    else:
        print("❌ Custom print job failed")
    
    # Summary
    print(f"\n📊 Results: Wireshark={'✅' if success1 else '❌'}, Custom={'✅' if success2 else '❌'}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()