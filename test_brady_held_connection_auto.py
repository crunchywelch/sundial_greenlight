#!/usr/bin/env python3
"""
Brady M511 Held Connection Test - Automatic Version  
Establishes connection and holds it open to verify LED behavior
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

async def test_held_connection(hold_duration: int = 45):
    """Test holding connection open to verify LED behavior"""
    
    print(f"🧪 Brady M511 Held Connection Test")
    print(f"=" * 50)
    print(f"⏱️  Will hold connection for {hold_duration} seconds")
    print(f"👁️  WATCH THE BRADY M511 PAIRING LED:")
    print(f"   • Before connection: Should be blinking/cycling")
    print(f"   • After connection: Should become SOLID (like Android app)")
    print(f"   • After disconnect: Should return to blinking")
    print()
    
    client = None
    try:
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
        print("🔗 CONNECTION ESTABLISHED!")
        print("=" * 30)
        print("👁️  CHECK THE PAIRING LED NOW:")
        print("   ✅ Should be SOLID (not blinking)")
        print("   ❌ If still blinking = connection not properly established")
        print()
        
        # Get connection details
        try:
            mtu = client.mtu_size
            print(f"📏 MTU: {mtu}")
        except:
            print(f"📏 MTU: Unknown")
        
        # Service discovery
        print("🔍 Discovering services...")
        services = client.services
        service_count = len(list(services))
        print(f"   📋 Found {service_count} services")
        
        # Find and verify Brady service
        brady_service = None
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                print(f"   ✅ Brady Service: {service.uuid}")
                
                char_count = len(service.characteristics)
                print(f"   📡 Brady Characteristics: {char_count}")
                
                for char in service.characteristics:
                    properties = ", ".join(char.properties)
                    char_name = "Unknown"
                    if "7d9d9a4d" in str(char.uuid).lower():
                        char_name = "Print Job"
                    elif "a61ae408" in str(char.uuid).lower():
                        char_name = "PICL Request"  
                    elif "786af345" in str(char.uuid).lower():
                        char_name = "PICL Response"
                    
                    print(f"      🔧 {char_name}: {char.uuid} ({properties})")
                break
        
        if not brady_service:
            print("   ❌ Brady service not found!")
            return False
        
        # Enable notifications like Android app
        picl_response_char = None
        for char in brady_service.characteristics:
            if str(char.uuid).lower() == PICL_RESPONSE_CHAR_UUID.lower():
                picl_response_char = char
                break
        
        notification_count = 0
        if picl_response_char and "indicate" in picl_response_char.properties:
            print("📬 Enabling PICL Response notifications (like Android app)...")
            
            def notification_handler(sender, data):
                nonlocal notification_count
                notification_count += 1
                timestamp = time.strftime("%H:%M:%S")
                print(f"   📨 [{timestamp}] Notification #{notification_count}: {len(data)} bytes")
                
                # Try to decode PICL response
                if len(data) >= 20:
                    try:
                        # Skip PICL header (16 bytes) and length (4 bytes)
                        json_data = data[20:].decode('utf-8', errors='ignore')
                        if json_data.startswith('{"PropertyGetResponses"'):
                            print(f"      📄 PICL Response: {json_data[:50]}...")
                        else:
                            print(f"      📄 Data: {data[:20].hex()}...")
                    except:
                        print(f"      📄 Raw data: {data[:20].hex()}...")
                else:
                    print(f"      📄 Data: {data.hex()}")
            
            await client.start_notify(picl_response_char, notification_handler)
            print("   ✅ Notifications enabled")
        else:
            print("   ⚠️  PICL Response notifications not available")
        
        print()
        print("⏳ HOLDING CONNECTION OPEN...")
        print("=" * 40)
        
        # Hold connection and monitor status
        start_hold = time.time()
        last_status_check = start_hold
        
        while time.time() - start_hold < hold_duration:
            remaining = hold_duration - (time.time() - start_hold)
            
            # Status update every 10 seconds
            if time.time() - last_status_check >= 10:
                if client.is_connected:
                    print(f"   ✅ [{time.strftime('%H:%M:%S')}] Connection active, {remaining:.0f}s remaining")
                else:
                    print(f"   ❌ [{time.strftime('%H:%M:%S')}] Connection lost!")
                    return False
                last_status_check = time.time()
            
            await asyncio.sleep(1)
        
        print()
        print("✅ CONNECTION HELD SUCCESSFULLY!")
        print("📊 Final Status:")
        print(f"   🔗 Connected: {client.is_connected}")
        print(f"   ⏱️  Duration: {hold_duration} seconds")
        print(f"   📬 Notifications received: {notification_count}")
        print(f"   📏 MTU: {mtu if 'mtu' in locals() else 'Unknown'}")
        
        return True
        
    except asyncio.TimeoutError:
        print("❌ Connection timeout - printer may not be responding")
        return False
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
        print("   (Connection was working)")
        return True
    except Exception as e:
        print(f"❌ Connection error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if client and client.is_connected:
            print("\n🔌 Disconnecting from Brady M511...")
            try:
                await client.disconnect()
                print("✅ Disconnected cleanly")
                print("👁️  LED should now return to blinking/cycling mode")
                print()
            except Exception as e:
                print(f"⚠️  Disconnect error: {e}")

async def main():
    """Main test function"""
    print("🧪 Brady M511 Connection LED Verification Test")
    print("=" * 60)
    print("This test establishes and holds a connection to verify proper")
    print("connection establishment by monitoring the pairing LED behavior.")
    print()
    print("📍 OBSERVE THE BRADY M511 PAIRING LED:")
    print("   Before: LED should be blinking/cycling (pairing mode)")  
    print("   During: LED should become SOLID when connected")
    print("   After:  LED should return to blinking when disconnected")
    print()
    print("🚀 Starting connection test in 3 seconds...")
    await asyncio.sleep(3)
    
    success = await test_held_connection(45)  # Hold for 45 seconds
    
    print("\n" + "="*60)
    print("📊 TEST RESULTS:")
    if success:
        print("✅ Connection established and held successfully")
        print("🔍 KEY VERIFICATION POINTS:")
        print("   1. Did the LED become SOLID during connection?")
        print("   2. Did the LED return to blinking after disconnect?")
        print("   3. Did we receive PICL notifications (like Android)?")
        print()
        print("If all LEDs behaved correctly, the connection works like Android!")
    else:
        print("❌ Connection test failed")
        print("🔧 This indicates the connection isn't properly established")
    
    print("\n🏁 Test completed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()