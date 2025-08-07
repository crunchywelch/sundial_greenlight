#!/usr/bin/env python3
"""
Direct Brady M511 connection test with detailed error reporting
"""

import asyncio
import logging
import traceback
from bleak import BleakClient

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Brady M511 Details
BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"

async def test_direct_connection():
    """Test direct connection with detailed error reporting"""
    print(f"🎯 Testing direct connection to Brady M511: {BRADY_MAC}")
    
    client = None
    try:
        print("  📡 Creating BleakClient...")
        client = BleakClient(BRADY_MAC, timeout=30.0)  # Longer timeout
        
        print("  ⏳ Attempting to connect...")
        await client.connect()
        
        print("  🔍 Checking connection status...")
        if client.is_connected:
            print("  ✅ Connection successful!")
            
            print("  📋 Getting service information...")
            try:
                services = client.services
                print(f"  📋 Found {len(services)} services:")
                
                for service in services:
                    print(f"    🔧 Service: {service.uuid}")
                    if "fd1c" in str(service.uuid).lower():
                        print("      ✅ This is the Brady service!")
                        
                        # List characteristics
                        for char in service.characteristics:
                            properties = ", ".join(char.properties)
                            print(f"        📡 Char: {char.uuid} ({properties})")
                            
            except Exception as e:
                print(f"  ❌ Service discovery error: {e}")
                traceback.print_exc()
            
            print("  ✅ All tests passed!")
            return True
            
        else:
            print("  ❌ Connection failed - client reports not connected")
            return False
            
    except asyncio.TimeoutError as e:
        print(f"  ⏱️  Connection timeout after 30 seconds")
        print(f"      Error details: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Connection error: {type(e).__name__}: {e}")
        print("  📋 Full error trace:")
        traceback.print_exc()
        return False
    finally:
        if client and client.is_connected:
            print("  🔌 Disconnecting...")
            try:
                await client.disconnect()
                print("  ✅ Disconnected successfully")
            except Exception as e:
                print(f"  ⚠️  Disconnect error: {e}")

async def main():
    """Main test function"""
    print("🧪 Direct Brady M511 Connection Test")
    print("=" * 50)
    
    success = await test_direct_connection()
    
    if success:
        print("\n✅ Direct connection test PASSED!")
    else:
        print("\n❌ Direct connection test FAILED!")
        print("\n🔧 Troubleshooting:")
        print("  1. Is the printer powered on?")
        print("  2. Is the printer in Bluetooth pairing mode?")
        print("  3. Is the printer already connected to another device?")
        print("  4. Try restarting the printer")
        print("  5. Check Bluetooth permissions and status")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        traceback.print_exc()