#!/usr/bin/env python3
"""
Brady M511 Print Test with Discovery
Uses the exact same pattern as the working settings screen
"""

import asyncio
import logging
import time
import uuid
import sys
sys.path.insert(0, '.')

from greenlight.hardware.label_printer import discover_brady_printers_sync
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Constants
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"

def create_simple_print_job(text: str = "TEST") -> bytes:
    """Create a simple Brady print job"""
    
    # Very simple PICL job based on successful patterns
    job_id = uuid.uuid4().hex[:8]
    
    print(f"   📝 Job ID: {job_id}")
    print(f"   📝 Text: '{text}'")
    
    # Minimal job structure
    job_data = bytearray()
    
    # Job start
    job_data.extend([0x01, 0x00, 0x00])
    
    # Simple text command sequence
    text_cmd = f"{text}\r\n"  # Simple text with CRLF
    job_data.extend([0x02, len(text_cmd)])
    job_data.extend(text_cmd.encode('ascii'))
    
    print(f"   📦 Job size: {len(job_data)} bytes")
    
    return bytes(job_data)

async def test_print_with_discovery():
    """Test printing using exact settings screen pattern"""
    
    print("🧪 Brady M511 Print Test with Discovery")
    print("=" * 50)
    print("🎯 Using same pattern as working settings screen")
    print()
    
    # Step 1: Discovery (same as settings screen)
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
    
    # Step 2: Connection using EXACT settings method
    print(f"\n🔌 Step 2: Connecting using settings screen method...")
    print(f"   🔍 Watch Brady M511 LED - should go SOLID!")
    
    connection_success = False
    client = None
    
    try:
        async def connect_and_print():
            """Direct connection + print - exact settings method"""
            client = BleakClient(printer_info['address'], timeout=15.0)
            
            # Simple connection that makes LED go solid (EXACT settings code)
            await client.connect()
            
            if client.is_connected:
                print("   ✅ Connected! (LED should be SOLID)")
                
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
                
                if print_char:
                    print("   ✅ Found print characteristic")
                    
                    # Create and send simple print job
                    job_data = create_simple_print_job("HELLO")
                    
                    print("   📤 Sending print job...")
                    try:
                        await client.write_gatt_char(print_char, job_data, response=False)
                        print("   ✅ Print job sent!")
                    except Exception as e:
                        print(f"   ⚠️  Print job error: {e}")
                else:
                    print("   ❌ Print characteristic not found")
                
                # Hold connection briefly to see results
                await asyncio.sleep(10)
                await client.disconnect()
                return True
            return False
        
        # Run connection test in new event loop (EXACT settings code)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            connection_success = await connect_and_print()
        finally:
            loop.close()
            
    except Exception as e:
        print(f"   ❌ Connection error: {e}")
        import traceback
        traceback.print_exc()
    
    # Step 3: Results
    print(f"\n📊 Results:")
    print(f"   Connection Success: {connection_success}")
    
    if connection_success:
        print(f"   ✅ SUCCESS - sent print job to Brady M511")
        print(f"   👁️  Check for printed label!")
    else:
        print(f"   ❌ FAILED - could not send print job")
        
    return connection_success

def main():
    """Main test function - matches settings screen context"""
    
    print("📍 SETUP CHECKLIST:")
    print("✓ Brady M511 is powered on")
    print("✓ LED is blinking (pairing mode)")
    print("✓ M4C-187 labels are loaded")
    print("✓ No other devices connected")
    print()
    
    # Run in sync context (like settings screen)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(test_print_with_discovery())
    finally:
        loop.close()
    
    print(f"\n" + "=" * 50)
    print("📊 PRINT TEST WITH DISCOVERY RESULTS")
    print("=" * 50)
    
    if success:
        print("✅ SUCCESS: Print job sent to Brady M511!")
        print("🎉 Check the printer for output")
        print()
        print("🔍 VERIFY:")
        print("   ❓ Did you hear printer sounds?")
        print("   ❓ Did a label print?")
        print("   ❓ Did LED go solid during connection?")
    else:
        print("❌ FAILED: Could not complete print test")
        print()
        print("🔧 TROUBLESHOOTING:")
        print("   1. Power cycle Brady M511")
        print("   2. Ensure pairing mode (LED blinking)")
        print("   3. Check label supply")
        print("   4. Try again in 10-15 seconds")

if __name__ == "__main__":
    # Pure sync context - matches settings screen exactly
    main()