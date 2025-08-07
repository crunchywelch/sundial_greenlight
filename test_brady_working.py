#!/usr/bin/env python3
"""
Working Brady M511 connection test - demonstrating successful connection
"""

import asyncio
import logging
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"

# Expected Brady M511 characteristics
BRADY_CHARS = {
    "7d9d9a4d-b530-4d13-8d61-e0ff445add19": "Print Job Characteristic",
    "a61ae408-3273-420c-a9db-0669f4f23b69": "PICL Request Characteristic",
    "786af345-1b68-c594-c643-e2867da117e3": "PICL Response Characteristic"
}

async def test_working_connection():
    """Test the now-working Brady M511 connection"""
    print(f"🎯 Testing working Brady M511 connection: {BRADY_MAC}")
    
    client = None
    try:
        print("  📡 Creating BleakClient...")
        client = BleakClient(BRADY_MAC, timeout=10.0)
        
        print("  ⏳ Connecting...")
        await client.connect()
        
        if not client.is_connected:
            print("  ❌ Connection failed")
            return False
            
        print("  ✅ Connection successful!")
        
        # Get services
        print("  🔍 Discovering services...")
        services = client.services
        service_count = len(list(services))
        print(f"  📋 Found {service_count} services:")
        
        brady_service = None
        for service in services:
            service_name = str(service.uuid)
            if "fd1c" in service_name.lower():
                brady_service = service
                print(f"    ✅ Brady Service: {service.uuid}")
            else:
                print(f"    🔧 Service: {service.uuid}")
        
        if not brady_service:
            print("  ❌ Brady service not found!")
            return False
            
        # Check Brady characteristics
        print("  🔍 Checking Brady characteristics...")
        found_chars = {}
        
        for char in brady_service.characteristics:
            char_uuid = str(char.uuid).lower()
            char_name = BRADY_CHARS.get(char_uuid, "Unknown")
            properties = ", ".join(char.properties)
            
            print(f"    📡 {char.uuid}")
            print(f"        Name: {char_name}")  
            print(f"        Properties: {properties}")
            
            if char_uuid in BRADY_CHARS:
                found_chars[char_uuid] = char
        
        # Verify all expected characteristics found
        missing_chars = set(BRADY_CHARS.keys()) - set(found_chars.keys())
        if missing_chars:
            print(f"  ⚠️  Missing characteristics: {missing_chars}")
        else:
            print("  ✅ All expected Brady characteristics found!")
        
        # Test notification capability
        picl_response_char = found_chars.get("786af345-1b68-c594-c643-e2867da117e3")
        if picl_response_char and "indicate" in picl_response_char.properties:
            print("  📬 Testing PICL Response notifications...")
            
            notifications_received = []
            
            def notification_handler(sender, data):
                notifications_received.append(data)
                print(f"    📨 Notification received: {len(data)} bytes")
                print(f"    📄 Data: {data.hex() if len(data) <= 20 else data[:20].hex() + '...'}")
            
            try:
                await client.start_notify(picl_response_char, notification_handler)
                print("    ✅ Notifications enabled")
                
                # Wait briefly for any automatic notifications
                await asyncio.sleep(2.0)
                
                await client.stop_notify(picl_response_char)
                print(f"    📬 Notifications stopped ({len(notifications_received)} received)")
                
            except Exception as e:
                print(f"    ❌ Notification test failed: {e}")
        
        print("  ✅ Brady M511 connection test PASSED!")
        return True
        
    except Exception as e:
        print(f"  ❌ Connection test failed: {e}")
        return False
    finally:
        if client and client.is_connected:
            print("  🔌 Disconnecting...")
            await client.disconnect()
            print("  ✅ Disconnected")

async def main():
    """Main test"""
    print("🧪 Brady M511 Working Connection Test")
    print("=" * 50)
    print("Demonstrating successful Brady M511 BLE connection")
    print()
    
    success = await test_working_connection()
    
    if success:
        print("\n🎉 SUCCESS! Brady M511 connection is now working!")
        print("\n📋 Next Steps:")
        print("  1. Implement PICL protocol communication")
        print("  2. Test property subscriptions") 
        print("  3. Test print job sending")
        print("  4. Integrate into main application")
    else:
        print("\n❌ Connection test failed")
        print("\n🔧 If this fails, try:")
        print("  1. bluetoothctl pairable on")
        print("  2. bluetoothctl remove 88:8C:19:00:E2:49") 
        print("  3. Power cycle the printer")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")