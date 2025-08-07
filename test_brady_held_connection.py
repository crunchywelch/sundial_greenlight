#!/usr/bin/env python3
"""
Brady M511 Held Connection Test
Establishes connection and holds it open to verify LED behavior
Should make the pairing LED stay solid like the Android app
"""

import asyncio
import logging
import time
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"
PICL_RESPONSE_CHAR_UUID = "786af345-1b68-c594-c643-e2867da117e3"

async def test_held_connection(hold_duration: int = 60):
    """
    Test holding connection open to verify LED behavior
    
    Args:
        hold_duration: How long to hold the connection in seconds
    """
    
    print(f"🧪 Brady M511 Held Connection Test")
    print(f"=" * 50)
    print(f"⏱️  Will hold connection for {hold_duration} seconds")
    print(f"👁️  Watch the Brady M511 pairing LED - it should stay solid when connected")
    print()
    
    client = None
    try:
        # Connect with extended timeout
        print(f"🔌 Connecting to Brady M511 at {BRADY_MAC}...")
        client = BleakClient(BRADY_MAC, timeout=20.0)
        
        connection_start = time.time()
        await client.connect()
        connection_time = time.time() - connection_start
        
        if not client.is_connected:
            print("❌ Connection failed - client reports not connected")
            return False
        
        print(f"✅ Connected successfully in {connection_time:.2f} seconds!")
        print()
        
        # Get detailed connection info
        print("📋 Connection Details:")
        try:
            # Check MTU
            mtu = client.mtu_size
            print(f"   📏 MTU: {mtu}")
        except:
            print(f"   📏 MTU: Unknown")
        
        # Service discovery
        print("🔍 Discovering services...")
        services = client.services
        service_count = len(list(services))
        print(f"   📋 Found {service_count} services")
        
        # Find Brady service
        brady_service = None
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                print(f"   ✅ Brady Service: {service.uuid}")
                
                # List Brady characteristics
                for char in service.characteristics:
                    properties = ", ".join(char.properties)
                    print(f"      📡 {char.uuid} ({properties})")
                break
        
        if not brady_service:
            print("   ❌ Brady service not found!")
            return False
        
        # Enable notifications on PICL Response (like Android app does)
        picl_response_char = None
        for char in brady_service.characteristics:
            if str(char.uuid).lower() == PICL_RESPONSE_CHAR_UUID.lower():
                picl_response_char = char
                break
        
        if picl_response_char and "indicate" in picl_response_char.properties:
            print("📬 Enabling PICL Response notifications...")
            
            notification_count = 0
            def notification_handler(sender, data):
                nonlocal notification_count
                notification_count += 1
                print(f"   📨 Notification #{notification_count}: {len(data)} bytes")
                # Show first few bytes
                if len(data) > 20:
                    print(f"      Data preview: {data[:20].hex()}...")
                else:
                    print(f"      Data: {data.hex()}")
            
            await client.start_notify(picl_response_char, notification_handler)
            print("   ✅ Notifications enabled")
        
        print()
        print("🔗 CONNECTION ESTABLISHED AND ACTIVE")
        print("=" * 50)
        print("👁️  CHECK THE BRADY M511 PAIRING LED NOW:")
        print("   ✅ LED should be SOLID (not blinking) - like Android app")
        print("   ❌ If LED is still blinking, connection isn't fully established")
        print()
        
        # Hold the connection open
        print(f"⏳ Holding connection for {hold_duration} seconds...")
        print("   (Press Ctrl+C to end early)")
        
        for remaining in range(hold_duration, 0, -5):
            print(f"   ⏱️  {remaining}s remaining... (LED should stay solid)")
            
            # Check connection status
            if not client.is_connected:
                print("   ❌ Connection lost!")
                return False
                
            await asyncio.sleep(5)
        
        print()
        print("✅ Connection held successfully!")
        print("📊 Final Status:")
        print(f"   🔗 Connected: {client.is_connected}")
        print(f"   📬 Notifications received: {notification_count if 'notification_count' in locals() else 0}")
        
        return True
        
    except asyncio.TimeoutError:
        print("❌ Connection timeout - printer may not be in pairing mode")
        return False
    except KeyboardInterrupt:
        print("\n⏹️  Connection test interrupted by user")
        print("   (This is normal - connection was working)")
        return True
    except Exception as e:
        print(f"❌ Connection error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client and client.is_connected:
            print("🔌 Disconnecting...")
            try:
                await client.disconnect()
                print("✅ Disconnected cleanly")
                print("👁️  LED should now return to blinking/cycling mode")
            except Exception as e:
                print(f"⚠️  Disconnect error: {e}")

async def test_multiple_connections():
    """Test multiple quick connections like multi-app usage"""
    print(f"\n🔄 Testing Multiple Quick Connections")
    print(f"=" * 40)
    print("Testing Brady's multi-app design with repeated connections")
    
    for attempt in range(3):
        print(f"\n🎯 Connection Attempt #{attempt + 1}")
        
        try:
            client = BleakClient(BRADY_MAC, timeout=10.0)
            
            start_time = time.time()
            await client.connect()
            connect_time = time.time() - start_time
            
            if client.is_connected:
                print(f"   ✅ Connected in {connect_time:.2f}s")
                
                # Hold briefly to observe LED
                print(f"   ⏱️  Holding for 10 seconds...")
                await asyncio.sleep(10)
                
                await client.disconnect()
                print(f"   🔌 Disconnected")
                
                # Brief pause before next attempt
                if attempt < 2:
                    print(f"   ⏳ Waiting 5s before next attempt...")
                    await asyncio.sleep(5)
            else:
                print(f"   ❌ Connection failed")
                
        except Exception as e:
            print(f"   ❌ Attempt failed: {e}")

async def main():
    """Main test function"""
    print("🧪 Brady M511 Connection Verification Test")
    print("=" * 60)
    print("This test verifies proper connection establishment")
    print("by holding the connection open and monitoring LED behavior")
    print()
    
    # Test 1: Long held connection
    print("📍 SETUP INSTRUCTIONS:")
    print("1. Ensure Brady M511 is powered on")
    print("2. Observe the pairing LED - should be blinking/cycling")
    print("3. Run this test and watch the LED behavior")
    print()
    
    input("Press Enter when ready to start connection test...")
    
    success = await test_held_connection(60)  # Hold for 60 seconds
    
    if success:
        print("\n✅ Connection test completed!")
        
        # Ask for LED confirmation
        print("\n❓ LED Behavior Verification:")
        led_solid = input("Did the LED stay SOLID while connected? (y/n): ").lower().startswith('y')
        
        if led_solid:
            print("🎉 SUCCESS! Connection is working like Android app")
        else:
            print("⚠️  WARNING: LED behavior doesn't match Android app")
            print("   This suggests the connection isn't fully established")
    else:
        print("\n❌ Connection test failed")
    
    # Test 2: Multiple connections  
    print("\n" + "="*60)
    multi_test = input("Run multiple connection test? (y/n): ").lower().startswith('y')
    if multi_test:
        await test_multiple_connections()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()