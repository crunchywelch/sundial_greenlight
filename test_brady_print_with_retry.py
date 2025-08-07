#!/usr/bin/env python3
"""
Brady M511 Print Test with Retry Logic
Based on Wireshark analysis showing "Unknown Connection Identifier (0x02)" error
This indicates the Brady M511's multi-app cycling behavior
"""

import asyncio
import logging
import time
import uuid
import sys
sys.path.insert(0, '.')

from greenlight.hardware.label_printer import discover_brady_printers_sync
from bleak import BleakClient
from bleak.exc import BleakError

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Constants
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"

def create_simple_print_job(text: str = "TEST") -> bytes:
    """Create a simple Brady print job"""
    
    job_id = uuid.uuid4().hex[:8]
    
    print(f"   📝 Job ID: {job_id}")
    print(f"   📝 Text: '{text}'")
    
    # Simple PICL-style job
    job_data = bytearray()
    
    # Job start marker
    job_data.extend([0x01, 0x00, 0x00])
    
    # Simple text command
    text_cmd = f"{text}\r\n"
    job_data.extend([0x02, len(text_cmd)])
    job_data.extend(text_cmd.encode('ascii'))
    
    print(f"   📦 Job size: {len(job_data)} bytes")
    
    return bytes(job_data)

async def brady_connection_with_retry(printer_address: str, max_retries: int = 5) -> tuple:
    """
    Connect to Brady M511 with retry logic for multi-app cycling
    
    Based on Wireshark analysis showing "Unknown Connection Identifier (0x02)"
    This happens when Brady M511 cycles its connection availability
    """
    
    for attempt in range(max_retries):
        print(f"   🔄 Connection attempt {attempt + 1}/{max_retries}")
        
        client = None
        try:
            client = BleakClient(printer_address, timeout=10.0)  # Shorter timeout per attempt
            
            print(f"      ⏳ Connecting to {printer_address}...")
            start_time = time.time()
            
            await client.connect()
            
            connection_time = time.time() - start_time
            
            if client.is_connected:
                print(f"      ✅ Connected in {connection_time:.2f}s (LED should be SOLID)")
                return client, True
            else:
                print(f"      ❌ Connection failed (client not connected)")
                
        except asyncio.TimeoutError:
            print(f"      ⏰ Timeout after 10s (Brady cycling - normal behavior)")
        except BleakError as e:
            if "Unknown Connection Identifier" in str(e):
                print(f"      🔄 Brady M511 cycling detected (0x02 error)")
            else:
                print(f"      ❌ BLE error: {e}")
        except Exception as e:
            print(f"      ❌ Unexpected error: {e}")
        
        # Clean up failed connection
        if client:
            try:
                if client.is_connected:
                    await client.disconnect()
            except:
                pass
        
        # Wait before retry (Brady M511 cycles every ~10-15 seconds)
        if attempt < max_retries - 1:
            wait_time = 3 + (attempt * 2)  # Increasing wait: 3s, 5s, 7s, 9s
            print(f"      ⏸️  Waiting {wait_time}s for Brady M511 to cycle...")
            await asyncio.sleep(wait_time)
    
    print(f"   ❌ All {max_retries} connection attempts failed")
    return None, False

async def test_print_with_retry():
    """Test printing with Brady M511 multi-app retry logic"""
    
    print("🧪 Brady M511 Print Test with Retry Logic")
    print("=" * 50)
    print("🎯 Handles Brady M511 multi-app cycling behavior")
    print("📊 Based on Wireshark analysis of connection failures")
    print()
    
    # Step 1: Discovery
    print("📍 Step 1: Discovering Brady printers...")
    try:
        printers = discover_brady_printers_sync()
        
        if not printers:
            print("   ❌ No Brady printers found")
            return False
            
        printer_info = printers[0]
        print(f"   ✅ Found: {printer_info['name']} at {printer_info['address']}")
        
    except Exception as e:
        print(f"   ❌ Discovery error: {e}")
        return False
    
    # Step 2: Connection with retry logic
    print(f"\n🔌 Step 2: Multi-app connection with retry...")
    print(f"   📝 Brady M511 cycles connection availability every ~10-15s")
    print(f"   📝 This is normal behavior for multi-app printers")
    print(f"   🔍 Watch LED - should go SOLID when connection succeeds")
    print()
    
    client = None
    try:
        client, connected = await brady_connection_with_retry(printer_info['address'])
        
        if not connected:
            print("   ❌ Failed to connect after all retries")
            return False
        
        # Step 3: Send print job
        print(f"\n🖨️  Step 3: Sending print job...")
        
        # Find print characteristic
        services = client.services
        print_char = None
        
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                for char in service.characteristics:
                    if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                        print_char = char
                        break
                break
        
        if not print_char:
            print("   ❌ Print characteristic not found")
            return False
        
        print("   ✅ Found print characteristic")
        
        # Create and send print job
        job_data = create_simple_print_job("HELLO")
        
        print("   📤 Sending print job...")
        try:
            await client.write_gatt_char(print_char, job_data, response=False)
            print("   ✅ Print job sent successfully!")
        except Exception as e:
            print(f"   ❌ Print job send error: {e}")
            return False
        
        # Step 4: Hold connection and observe
        print(f"\n⏳ Step 4: Holding connection for 15 seconds...")
        print("   👁️  OBSERVE:")
        print("   • Brady M511 LED should stay SOLID")
        print("   • Listen for printer sounds (motor, feeding)")
        print("   • Check for label output")
        print()
        
        for i in range(15):
            if client.is_connected:
                remaining = 15 - i
                print(f"   ⏰ Connection active, {remaining}s remaining...")
            else:
                print("   ❌ Connection lost!")
                return False
            await asyncio.sleep(1)
        
        print("\n✅ PRINT TEST WITH RETRY COMPLETED!")
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

def main():
    """Main test function"""
    
    print("📍 BRADY M511 MULTI-APP BEHAVIOR:")
    print("• Brady M511 cycles connection availability")
    print("• This is normal for printers that support multiple apps")
    print("• Connection may take 2-5 attempts")
    print("• Each attempt uses different timing")
    print()
    print("📍 SETUP CHECKLIST:")
    print("✓ Brady M511 is powered on")
    print("✓ LED is blinking (pairing mode)")
    print("✓ M4C-187 labels are loaded")
    print("✓ No other Brady apps are actively connected")
    print()
    
    # Run test
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(test_print_with_retry())
    finally:
        loop.close()
    
    print(f"\n" + "=" * 50)
    print("📊 BRADY PRINT TEST WITH RETRY RESULTS")
    print("=" * 50)
    
    if success:
        print("✅ SUCCESS: Print job sent with retry logic!")
        print("🎉 Brady M511 multi-app cycling handled correctly")
        print()
        print("🔍 VERIFY RESULTS:")
        print("   ❓ Did you hear printer sounds?")
        print("   ❓ Did a label print with 'HELLO' text?")
        print("   ❓ Did LED go solid during connection?")
        print()
        print("📝 TECHNICAL SUCCESS:")
        print("   • Connection retry logic works")
        print("   • Brady M511 cycling behavior handled")
        print("   • Print job successfully delivered")
    else:
        print("❌ FAILED: Could not complete print test")
        print()
        print("🔧 TROUBLESHOOTING:")
        print("   1. Ensure Brady M511 is in pairing mode")
        print("   2. Check no other Brady apps are running")
        print("   3. Power cycle printer if needed")
        print("   4. Brady may need 5-10 minutes between major test sessions")

if __name__ == "__main__":
    main()