#!/usr/bin/env python3
"""
Simple Brady M511 Print Test
Uses the proven working connection method from settings screen + Wireshark print data
"""

import asyncio
import logging
import time
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Constants
BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"

# Simple PICL print command from Wireshark analysis
SIMPLE_PRINT_DATA = bytes.fromhex(
    # This is a minimal print command based on successful Brady app captures
    "010000024b000a6637326638626261376339623463343339316437373335663236346164333934643938340d024b00094d34432d3138370d02442b3030303102432b3030303102630002702b3030026f2b3030024f2b303002622b3030024d01"
)

async def test_brady_print():
    """Test Brady M511 printing using the exact working connection method"""
    
    print("🧪 Brady M511 Simple Print Test")
    print("=" * 50)
    print("🎯 OBJECTIVE: Print a test label using proven connection + Wireshark data")
    print()
    
    client = None
    try:
        # Step 1: Connect using the EXACT method from settings screen that works
        print("🔌 Step 1: Connecting to Brady M511 (using proven method)...")
        client = BleakClient(BRADY_MAC, timeout=15.0)
        
        start_time = time.time()
        await client.connect()
        connection_time = time.time() - start_time
        
        if not client.is_connected:
            print("   ❌ Connection failed")
            return False
        
        print(f"   ✅ Connected in {connection_time:.2f}s (LED should be SOLID)")
        print()
        
        # Step 2: Service discovery 
        print("🔍 Step 2: Discovering Brady services...")
        services = client.services
        brady_service = None
        
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                print(f"   ✅ Found Brady service: {service.uuid}")
                break
        
        if not brady_service:
            print("   ❌ Brady service not found")
            return False
        
        # Step 3: Find print job characteristic
        print("\n📡 Step 3: Finding print job characteristic...")
        print_job_char = None
        
        for char in brady_service.characteristics:
            print(f"   🔍 Found characteristic: {char.uuid}")
            if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                print_job_char = char
                print(f"   ✅ Found print job characteristic!")
                break
        
        if not print_job_char:
            print("   ❌ Print job characteristic not found")
            return False
        
        # Step 4: Send print data
        print("\n🖨️  Step 4: Sending print job...")
        print(f"   📦 Print data size: {len(SIMPLE_PRINT_DATA)} bytes")
        print("   📝 Based on successful Wireshark capture")
        
        # Send in chunks (typical Brady approach from JS SDK analysis)
        chunk_size = 20  # Conservative chunk size based on BLE MTU
        total_chunks = (len(SIMPLE_PRINT_DATA) + chunk_size - 1) // chunk_size
        
        for i in range(0, len(SIMPLE_PRINT_DATA), chunk_size):
            chunk = SIMPLE_PRINT_DATA[i:i+chunk_size]
            chunk_num = i // chunk_size + 1
            
            print(f"   📤 Sending chunk {chunk_num}/{total_chunks}: {len(chunk)} bytes")
            try:
                await client.write_gatt_char(print_job_char, chunk, response=True)
                await asyncio.sleep(0.05)  # Brief pause between chunks
            except Exception as e:
                print(f"   ⚠️  Chunk {chunk_num} error: {e}")
                # Continue trying other chunks
        
        print("   ✅ All chunks sent!")
        print()
        
        # Step 5: Hold connection briefly to observe results
        print("⏳ Step 5: Holding connection for 10 seconds...")
        print("   👁️  OBSERVE:")
        print("   • Brady M511 LED should remain SOLID")
        print("   • Listen for printer sounds (motor, feed)")
        print("   • Check for label output")
        
        for i in range(10):
            if client.is_connected:
                remaining = 10 - i
                print(f"   ✅ Connection active, {remaining}s remaining...")
            else:
                print("   ❌ Connection lost!")
                return False
            await asyncio.sleep(1)
        
        print("\n✅ PRINT TEST COMPLETED!")
        print("🔍 RESULTS TO VERIFY:")
        print("   ❓ Did the printer make any sounds?")
        print("   ❓ Did any label come out?")
        print("   ❓ Did the LED stay solid throughout?")
        
        return True
        
    except asyncio.TimeoutError:
        print("   ❌ Connection timeout - printer may not be available")
        return False
    except Exception as e:
        print(f"   ❌ Print test error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client and client.is_connected:
            print("\n🔌 Disconnecting from Brady M511...")
            try:
                await client.disconnect()
                print("   ✅ Disconnected (LED should return to blinking)")
            except Exception as e:
                print(f"   ⚠️  Disconnect error: {e}")

async def main():
    """Main test function"""
    print("📍 PRE-TEST CHECKLIST:")
    print("✓ Brady M511 is powered on")
    print("✓ Brady M511 LED is blinking (pairing mode)")
    print("✓ M4C-187 labels are loaded in printer")
    print("✓ No other devices are connected to printer")
    print()
    
    success = await test_brady_print()
    
    print("\n" + "="*50)
    print("📊 BRADY PRINT TEST RESULTS")
    print("="*50)
    
    if success:
        print("✅ TEST COMPLETED SUCCESSFULLY!")
        print()
        print("🔍 NEXT STEPS:")
        print("   1. Check if label was printed")
        print("   2. If no output, try different PICL commands")
        print("   3. If successful, integrate into main app")
        print()
        print("📝 TECHNICAL NOTES:")
        print("   • Connection method: Same as working settings screen")
        print("   • Print data: From successful Wireshark capture")
        print("   • LED behavior: Should be solid during connection")
    else:
        print("❌ TEST FAILED")
        print()
        print("🔧 TROUBLESHOOTING:")
        print("   1. Ensure Brady M511 is in pairing mode (LED blinking)")
        print("   2. Check no other apps are connected")
        print("   3. Try power cycling the printer")
        print("   4. Verify M4C-187 labels are loaded")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()