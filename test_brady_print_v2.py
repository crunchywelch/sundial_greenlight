#!/usr/bin/env python3
"""
Brady M511 Print Test v2
Improved version with better characteristic writing and PICL protocol
"""

import asyncio
import logging
import time
import uuid
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Constants
BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"

# Minimal PICL print job based on Brady SDK analysis
def create_minimal_print_job(text: str = "TEST") -> bytes:
    """Create a minimal Brady print job using PICL protocol"""
    
    # Generate unique job ID
    job_id = uuid.uuid4().hex[:12]  # 12 character job ID
    
    print(f"   📝 Creating job ID: {job_id}")
    print(f"   📝 Label text: '{text}'")
    
    # Build PICL command sequence (based on Brady SDK reverse engineering)
    job_data = bytearray()
    
    # Job header - packet type 0x01 (job start)
    job_data.extend([0x01, 0x00, 0x00])  # Packet type, flags
    
    # Job ID command
    job_id_cmd = f"K\x00\x0a{job_id}\x0d"
    job_data.extend([0x02, len(job_id_cmd)])  # Section type, length
    job_data.extend(job_id_cmd.encode('ascii'))
    
    # Label type (M4C-187 for our Brady M511)
    label_cmd = "K\x00\x09M4C-187\x0d"
    job_data.extend([0x02, len(label_cmd)])
    job_data.extend(label_cmd.encode('ascii'))
    
    # Basic positioning commands (from working Brady apps)
    pos_commands = [
        "D+0001",  # Print density
        "C+0001",  # Cutter
        "c\x00",   # Copies  
        "p+00",    # Position
        "o+00",    # Origin
        "O+00",    # Offset
        "b+00",    # Backfeed
        "M\x01"    # Mode
    ]
    
    for cmd in pos_commands:
        job_data.extend([0x02, len(cmd)])
        job_data.extend(cmd.encode('ascii'))
    
    # Text content identifier
    content_id = f"K\x00\x0c{text.ljust(8, '0')[:8]}"
    job_data.extend([0x02, len(content_id)])
    job_data.extend(content_id.encode('ascii'))
    
    # Print commands
    print_commands = ["A", "Q", "a"]  # Action, Quality, activate
    for cmd in print_commands:
        job_data.extend([0x02, len(cmd)])
        job_data.extend(cmd.encode('ascii'))
    
    # Text formatting - basic label format
    text_format = f"IB{text}\x0d"  # Internal Bold + text + carriage return
    job_data.extend([0x02, len(text_format)])
    job_data.extend(text_format.encode('ascii'))
    
    print(f"   📦 Created job: {len(job_data)} bytes")
    
    return bytes(job_data)

async def test_brady_print_v2():
    """Test Brady M511 printing with improved protocol"""
    
    print("🧪 Brady M511 Print Test v2")
    print("=" * 50)
    print("🎯 OBJECTIVE: Print test label with improved PICL protocol")
    print()
    
    client = None
    try:
        # Step 1: Connection (using proven working method)
        print("🔌 Step 1: Connecting to Brady M511...")
        client = BleakClient(BRADY_MAC, timeout=15.0)
        
        await client.connect()
        
        if not client.is_connected:
            print("   ❌ Connection failed")
            return False
        
        print("   ✅ Connected successfully (LED should be SOLID)")
        print()
        
        # Step 2: Service and characteristic discovery
        print("🔍 Step 2: Finding Brady print characteristics...")
        services = client.services
        brady_service = None
        
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                break
        
        if not brady_service:
            print("   ❌ Brady service not found")
            return False
        
        print_job_char = None
        for char in brady_service.characteristics:
            if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                print_job_char = char
                break
        
        if not print_job_char:
            print("   ❌ Print job characteristic not found")
            return False
        
        print("   ✅ Found print job characteristic")
        print(f"   📋 Properties: {print_job_char.properties}")
        print()
        
        # Step 3: Create print job
        print("📝 Step 3: Creating minimal print job...")
        job_data = create_minimal_print_job("HELLO")
        
        # Step 4: Send print job (try different approaches)
        print("\n🖨️  Step 4: Sending print job...")
        
        # Method 1: Send as single packet (if small enough)
        if len(job_data) <= 20:  # Conservative MTU limit
            print("   📤 Method: Single packet")
            try:
                await client.write_gatt_char(print_job_char, job_data, response=False)
                print("   ✅ Single packet sent successfully")
            except Exception as e:
                print(f"   ❌ Single packet failed: {e}")
                return False
        else:
            # Method 2: Chunked sending without offset (write_without_response style)
            print("   📤 Method: Chunked (no response)")
            chunk_size = 20
            success_count = 0
            
            for i in range(0, len(job_data), chunk_size):
                chunk = job_data[i:i+chunk_size]
                chunk_num = i // chunk_size + 1
                total_chunks = (len(job_data) + chunk_size - 1) // chunk_size
                
                try:
                    print(f"      📦 Chunk {chunk_num}/{total_chunks}: {len(chunk)} bytes")
                    await client.write_gatt_char(print_job_char, chunk, response=False)
                    success_count += 1
                    await asyncio.sleep(0.05)  # Small delay
                except Exception as e:
                    print(f"      ⚠️  Chunk {chunk_num} error: {e}")
            
            if success_count > 0:
                print(f"   ✅ Sent {success_count} chunks successfully")
            else:
                print("   ❌ All chunks failed")
                return False
        
        # Step 5: Wait and observe
        print("\n⏳ Step 5: Observing printer response (15 seconds)...")
        print("   👁️  LISTEN FOR:")
        print("   • Motor sounds (label feeding)")
        print("   • Printing sounds")
        print("   • Label output")
        print("   • LED staying solid")
        print()
        
        for i in range(15):
            if client.is_connected:
                remaining = 15 - i
                print(f"   ⏰ {remaining}s remaining...")
            else:
                print("   ❌ Connection lost!")
                return False
            await asyncio.sleep(1)
        
        print("\n✅ PRINT TEST v2 COMPLETED!")
        return True
        
    except Exception as e:
        print(f"   ❌ Print test error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client and client.is_connected:
            print("\n🔌 Disconnecting...")
            try:
                await client.disconnect()
                print("   ✅ Disconnected (LED should return to blinking)")
            except:
                pass

async def main():
    """Main test function"""
    print("📍 SETUP CHECKLIST:")
    print("✓ Brady M511 powered on and LED blinking")
    print("✓ M4C-187 labels loaded")
    print("✓ No other devices connected")
    print()
    
    success = await test_brady_print_v2()
    
    print("\n" + "="*50)
    print("📊 PRINT TEST v2 RESULTS")
    print("="*50)
    
    if success:
        print("✅ TEST COMPLETED!")
        print()
        print("🔍 VERIFICATION:")
        print("   ❓ Did you hear motor/printing sounds?")
        print("   ❓ Did a label print with 'HELLO' text?")
        print("   ❓ Did the LED stay solid during the test?")
        print()
        if input("Did the test print a label? (y/n): ").lower().startswith('y'):
            print("🎉 SUCCESS! Brady M511 printing is working!")
        else:
            print("📝 Need to refine PICL protocol or data format")
    else:
        print("❌ TEST FAILED")
        print("🔧 Check Brady M511 connection and setup")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()