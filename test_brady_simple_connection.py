#!/usr/bin/env python3
"""
Simple Brady M511 connection test - direct connection attempt
Based on debug evidence that the printer is discoverable
"""

import asyncio
import logging
import time
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"

async def test_direct_connection():
    """Direct connection test with LED observation instructions"""
    print("🧪 Brady M511 Direct Connection Test")
    print("=" * 50)
    print("🎯 OBJECTIVE: Test connection and observe LED behavior")
    print()
    print("👁️  LED OBSERVATION GUIDE:")
    print("   BEFORE: LED should be blinking/cycling (pairing mode)")
    print("   DURING: LED should become SOLID when connected") 
    print("   AFTER:  LED should return to blinking when disconnected")
    print()
    
    client = None
    try:
        print(f"🔌 Attempting direct connection to {BRADY_MAC}...")
        client = BleakClient(BRADY_MAC, timeout=15.0)
        
        # Track connection timing
        start_time = time.time()
        print("   ⏳ Connecting...")
        
        await client.connect()
        
        connection_time = time.time() - start_time
        
        if not client.is_connected:
            print("   ❌ Connection failed - client reports not connected")
            return False
        
        print(f"   ✅ Connected successfully in {connection_time:.2f} seconds!")
        print()
        
        print("🔗 CONNECTION ACTIVE!")
        print("=" * 30)
        print("👁️  CHECK THE LED RIGHT NOW:")
        print("   🔍 Is the pairing LED SOLID (not blinking)?")
        print("   ✅ SOLID = Connection working like Android")
        print("   ❌ BLINKING = Connection not fully established")
        print()
        
        # Get basic connection info
        try:
            mtu = client.mtu_size
            print(f"📏 Connection MTU: {mtu}")
        except:
            print(f"📏 Connection MTU: Unknown")
        
        # Quick service discovery test
        print("🔍 Quick service discovery...")
        try:
            services = client.services
            service_count = len(list(services))
            print(f"   📋 Discovered {service_count} services")
            
            # Look for Brady service
            brady_found = False
            for service in services:
                if "fd1c" in str(service.uuid).lower():
                    brady_found = True
                    print(f"   ✅ Brady service found: {service.uuid}")
                    
                    # Count characteristics
                    char_count = len(service.characteristics)
                    print(f"   📡 Brady characteristics: {char_count}")
                    break
            
            if not brady_found:
                print(f"   ⚠️  Brady service not found (may still be discovering)")
                
        except Exception as e:
            print(f"   ⚠️  Service discovery issue: {e}")
        
        print()
        print("⏳ HOLDING CONNECTION FOR 30 SECONDS...")
        print("   (Observe LED behavior during this time)")
        
        # Hold connection and provide status updates
        for i in range(6):  # 6 x 5 seconds = 30 seconds
            remaining = 30 - (i * 5)
            
            if client.is_connected:
                timestamp = time.strftime("%H:%M:%S")
                print(f"   ✅ [{timestamp}] Connection active, {remaining}s remaining")
            else:
                print(f"   ❌ Connection lost after {i*5} seconds!")
                return False
            
            await asyncio.sleep(5)
        
        print()
        print("✅ CONNECTION HELD SUCCESSFULLY FOR 30 SECONDS!")
        return True
        
    except asyncio.TimeoutError:
        print("   ❌ Connection timeout after 15 seconds")
        print("   🔧 This suggests the printer is not accepting connections")
        return False
    except Exception as e:
        print(f"   ❌ Connection error: {e}")
        return False
    finally:
        if client and client.is_connected:
            print("\n🔌 Disconnecting from Brady M511...")
            try:
                await client.disconnect()
                print("✅ Disconnected successfully")
                print("👁️  LED should now return to blinking/cycling mode")
            except Exception as e:
                print(f"⚠️  Disconnect error: {e}")

async def main():
    """Main test function"""
    print("📍 SETUP CHECKLIST:")
    print("✓ Brady M511 is powered on")
    print("✓ Brady M511 LED is blinking (pairing mode)")
    print("✓ No other devices are connected to the printer")
    print()
    
    success = await test_direct_connection()
    
    print("\n" + "="*50)
    print("📊 TEST RESULTS")
    print("="*50)
    
    if success:
        print("✅ CONNECTION SUCCESS!")
        print()
        print("🔍 VERIFY LED BEHAVIOR:")
        print("   ❓ Did the LED become solid during connection?")
        print("   ❓ Did it return to blinking after disconnect?")
        print()
        print("If YES to both questions:")
        print("   🎉 Connection works exactly like Android app!")
        print("   📝 The pairing LED cycling is normal behavior")
        print("   ✅ Ready for production integration")
        print()
        print("If NO to either question:")
        print("   ⚠️  Connection may not be fully established")
        print("   🔧 Further investigation needed")
    else:
        print("❌ CONNECTION FAILED")
        print()
        print("🔧 TROUBLESHOOTING:")
        print("   1. Power cycle the Brady M511")
        print("   2. Ensure no other devices are connected")
        print("   3. Check if printer is in correct pairing mode")
        print("   4. Verify printer is within range")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        print("   (Connection was working if we got this far)")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()