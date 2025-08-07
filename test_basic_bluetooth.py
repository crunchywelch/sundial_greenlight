#!/usr/bin/env python3
"""
Very basic Bluetooth Low Energy test script
Tests fundamental bleak functionality and Bluetooth adapter status
"""

import asyncio
import logging
from bleak import BleakScanner, BleakClient
import sys

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

async def test_bluetooth_adapter():
    """Test if Bluetooth adapter is working"""
    print("🔧 Testing Bluetooth adapter...")
    
    try:
        # Simple scan to test adapter
        print("  ⏳ Quick scan (5 seconds)...")
        devices = await BleakScanner.discover(timeout=5.0)
        
        print(f"  ✅ Found {len(devices)} devices")
        
        # Show first few devices
        for i, device in enumerate(devices[:5]):
            name = device.name if device.name else "Unknown"
            rssi = getattr(device, 'rssi', 'N/A')
            print(f"    {i+1}. {name} ({device.address}) RSSI: {rssi}")
        
        if len(devices) > 5:
            print(f"    ... and {len(devices) - 5} more devices")
            
        return len(devices) > 0
        
    except Exception as e:
        print(f"  ❌ Bluetooth adapter test failed: {e}")
        return False

async def test_connection_to_any_device():
    """Try to connect to any available device to test GATT functionality"""
    print("\n🔗 Testing GATT connection to any connectable device...")
    
    try:
        # Scan for devices
        devices = await BleakScanner.discover(timeout=8.0)
        
        # Look for devices that might be connectable
        connectable_devices = []
        for device in devices:
            # Skip devices without names (usually not connectable)
            if device.name and len(device.name) > 0:
                connectable_devices.append(device)
        
        if not connectable_devices:
            print("  ⚠️  No devices with names found (may indicate connection issues)")
            return False
        
        # Try to connect to the first few devices
        for i, device in enumerate(connectable_devices[:3]):
            print(f"  🎯 Attempting connection to {device.name} ({device.address})...")
            
            try:
                client = BleakClient(device.address, timeout=10.0)
                await client.connect()
                
                if client.is_connected:
                    print(f"    ✅ Connected successfully to {device.name}!")
                    
                    # Quick service discovery
                    services = client.services
                    print(f"    📋 Found {len(services)} services")
                    
                    await client.disconnect()
                    print(f"    🔌 Disconnected from {device.name}")
                    return True
                else:
                    print(f"    ❌ Connection failed to {device.name}")
                    
            except asyncio.TimeoutError:
                print(f"    ⏱️  Connection timeout to {device.name}")
            except Exception as e:
                print(f"    ❌ Connection error to {device.name}: {e}")
        
        print("  ❌ Could not connect to any devices")
        return False
        
    except Exception as e:
        print(f"  ❌ GATT test failed: {e}")
        return False

async def test_specific_mac(mac_address):
    """Test connection to specific MAC address"""
    print(f"\n🎯 Testing connection to specific MAC: {mac_address}")
    
    try:
        client = BleakClient(mac_address, timeout=15.0)
        
        print("  ⏳ Connecting...")
        await client.connect()
        
        if client.is_connected:
            print("  ✅ Connection successful!")
            
            # Service discovery
            print("  🔍 Discovering services...")
            services = client.services
            print(f"  📋 Found {len(services)} services:")
            
            for service in services:
                print(f"    🔧 {service.uuid}")
                for char in service.characteristics:
                    properties = ", ".join(char.properties)
                    print(f"      📡 {char.uuid} ({properties})")
            
            await client.disconnect()
            print("  🔌 Disconnected")
            return True
        else:
            print("  ❌ Connection failed")
            return False
            
    except asyncio.TimeoutError:
        print("  ⏱️  Connection timeout")
        return False
    except Exception as e:
        print(f"  ❌ Connection error: {e}")
        return False

def print_system_info():
    """Print system Bluetooth information"""
    print("🖥️  System Information:")
    print(f"  Python version: {sys.version}")
    
    try:
        import platform
        print(f"  OS: {platform.system()} {platform.release()}")
    except:
        pass
    
    try:
        import bleak
        print(f"  Bleak version: {bleak.__version__}")
    except:
        print("  Bleak version: Unknown")

async def main():
    """Main test function"""
    print("🧪 Basic Bluetooth Low Energy Test")
    print("=" * 40)
    
    print_system_info()
    print()
    
    # Test 1: Bluetooth adapter
    adapter_ok = await test_bluetooth_adapter()
    
    if not adapter_ok:
        print("\n❌ Bluetooth adapter test failed. Check:")
        print("  - Is Bluetooth enabled?")
        print("  - Are you running as root/with permissions?")
        print("  - Is bluetoothd service running?")
        return
    
    # Test 2: GATT connections
    gatt_ok = await test_connection_to_any_device()
    
    if gatt_ok:
        print("\n✅ Basic GATT functionality working!")
    else:
        print("\n⚠️  GATT connections failing")
    
    # Test 3: Manual MAC address test
    print("\n" + "=" * 40)
    print("Manual MAC Address Test")
    print("Enter a specific MAC address to test connection:")
    print("(Press Enter to skip)")
    
    try:
        mac = input("MAC Address (XX:XX:XX:XX:XX:XX): ").strip().upper()
        if mac and len(mac) == 17:  # Basic MAC format check
            await test_specific_mac(mac)
        elif mac:
            print("Invalid MAC address format")
    except KeyboardInterrupt:
        print("\n👋 Test interrupted")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()