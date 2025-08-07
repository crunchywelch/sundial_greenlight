#!/usr/bin/env python3
"""
Enhanced Brady M511 connection test based on Wireshark analysis
Tests the exact connection sequence observed from successful Android connection
"""

import asyncio
import logging
from bleak import BleakScanner, BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Details from Wireshark Analysis
BRADY_M511_NAME = "M511-PGM5112423102007"
BRADY_M511_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"

# Characteristics discovered from Wireshark (handle -> UUID mapping)
BRADY_CHARACTERISTICS = {
    # From the bundle.pretty.js analysis - these are the correct UUIDs
    "7d9d9a4d-b530-4d13-8d61-e0ff445add19": "Print Job Characteristic",
    "a61ae408-3273-420c-a9db-0669f4f23b69": "PICL Request Characteristic", 
    "786af345-1b68-c594-c643-e2867da117e3": "PICL Response Characteristic",
    # Additional characteristics found in Wireshark
    "19dd5a44-ffe0-618d-134d-30b5-4d9a9d7d": "Unknown Characteristic 1",
    "693bf2f4-6906-dba9-0c42-7332-08e41aa6": "Unknown Characteristic 2", 
    "e317a17d-86e2-43c6-94c5-681b45f36a78": "Unknown Characteristic 3"
}

async def enhanced_scan():
    """Enhanced scan specifically looking for our Brady printer"""
    print("🔍 Enhanced scan for Brady M511...")
    print(f"   Looking for: {BRADY_M511_NAME} ({BRADY_M511_MAC})")
    
    try:
        devices = await BleakScanner.discover(timeout=15.0)
        
        brady_found = False
        for device in devices:
            print(f"📱 Found: {device.name} ({device.address}) RSSI: {getattr(device, 'rssi', 'N/A')}")
            
            # Check for Brady M511 specifically
            if (device.name and "M511" in device.name) or device.address.upper() == BRADY_M511_MAC:
                brady_found = True
                print(f"✅ TARGET FOUND: {device.name} ({device.address})")
                
                # Show basic device details
                print("📋 Device Details:")
                print(f"    Address: {device.address}")
                print(f"    Name: {device.name}")
                print(f"    RSSI: {getattr(device, 'rssi', 'N/A')}")
                        
                return device
        
        if not brady_found:
            print("❌ Brady M511 not found in scan")
            print("🔧 Try putting the printer in pairing mode")
            
        return None
        
    except Exception as e:
        print(f"❌ Enhanced scan failed: {e}")
        return None

async def enhanced_connection_test(device):
    """Test connection with Android-observed parameters"""
    print(f"\n🔌 Enhanced connection test to {device.name}...")
    
    # Use connection parameters similar to Android
    client = BleakClient(
        device.address,
        timeout=20.0,  # Android took ~2 seconds, give us more time
    )
    
    try:
        print("  ⏳ Connecting with enhanced parameters...")
        await client.connect()
        
        if not client.is_connected:
            print("  ❌ Connection failed - client not connected")
            return False
            
        print("  ✅ Connection successful!")
        
        # Test MTU negotiation (Android requested 156, got 517)
        print("  📏 Testing MTU...")
        try:
            # Get current MTU 
            mtu = client.mtu_size
            print(f"    Current MTU: {mtu}")
        except:
            print("    MTU info not available")
        
        # Service discovery
        print("  🔍 Enhanced service discovery...")
        services = client.services
        print(f"  📋 Found {len(services)} services:")
        
        brady_service = None
        for service in services:
            service_name = str(service.uuid).upper()
            if "FD1C" in service_name:
                brady_service = service
                print(f"    ✅ BRADY SERVICE: {service.uuid}")
            else:
                print(f"    🔧 Service: {service.uuid}")
                
            # List characteristics for each service
            for char in service.characteristics:
                char_uuid = str(char.uuid).lower()
                char_name = BRADY_CHARACTERISTICS.get(char_uuid, "Unknown")
                properties = ", ".join(char.properties)
                print(f"      📡 {char.uuid} ({char_name}) - {properties}")
        
        if not brady_service:
            print("  ❌ Brady service not found!")
            return False
            
        print("  ✅ Brady service found and accessible!")
        
        # Test characteristic access
        print("  🧪 Testing characteristic access...")
        
        picl_response_char = None
        picl_request_char = None
        print_job_char = None
        
        for char in brady_service.characteristics:
            char_uuid = str(char.uuid).lower()
            
            if char_uuid == "786af345-1b68-c594-c643-e2867da117e3":
                picl_response_char = char
                print("    ✅ Found PICL Response characteristic")
            elif char_uuid == "a61ae408-3273-420c-a9db-0669f4f23b69":
                picl_request_char = char  
                print("    ✅ Found PICL Request characteristic")
            elif char_uuid == "7d9d9a4d-b530-4d13-8d61-e0ff445add19":
                print_job_char = char
                print("    ✅ Found Print Job characteristic")
        
        # Test notification enable (like Android does)
        if picl_response_char and "notify" in picl_response_char.properties:
            print("  📬 Testing notifications...")
            try:
                def notification_handler(sender, data):
                    print(f"    📨 Notification: {len(data)} bytes: {data.hex()}")
                
                await client.start_notify(picl_response_char, notification_handler)
                print("    ✅ Notifications enabled successfully!")
                
                # Wait a moment to see if we get any notifications
                await asyncio.sleep(2.0)
                
                await client.stop_notify(picl_response_char)
                print("    📬 Notifications stopped")
            except Exception as e:
                print(f"    ❌ Notification test failed: {e}")
        
        print("  ✅ Enhanced connection test successful!")
        return True
        
    except Exception as e:
        print(f"  ❌ Enhanced connection failed: {e}")
        return False
        
    finally:
        if client.is_connected:
            await client.disconnect()
            print("  🔌 Disconnected")

async def test_specific_brady_mac():
    """Test connection to the specific MAC from Wireshark"""
    print(f"\n🎯 Testing specific Brady MAC: {BRADY_M511_MAC}")
    
    class FakeBradyDevice:
        def __init__(self):
            self.name = "M511-Test"
            self.address = BRADY_M511_MAC
    
    device = FakeBradyDevice()
    return await enhanced_connection_test(device)

async def main():
    """Enhanced main test"""
    print("🧪 Enhanced Brady M511 Connection Test")
    print("=" * 50)
    print("Based on Android app Wireshark analysis")
    print()
    
    # Method 1: Enhanced scan
    device = await enhanced_scan()
    
    if device:
        success = await enhanced_connection_test(device)
        if success:
            print("\n✅ Enhanced connection test PASSED!")
            return
        else:
            print("\n❌ Enhanced connection test FAILED!")
    
    # Method 2: Direct MAC test
    print("\n" + "="*30)
    print("Trying direct MAC address connection...")
    success = await test_specific_brady_mac()
    
    if success:
        print("\n✅ Direct MAC connection PASSED!")
    else:
        print("\n❌ All connection attempts FAILED!")
        print("\n🔧 Troubleshooting tips:")
        print("  1. Ensure printer is in pairing mode")
        print("  2. Check if printer is connected to another device")  
        print("  3. Try power cycling the printer")
        print("  4. Check Bluetooth permissions")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()