#!/usr/bin/env python3
"""
Basic BLE connection test for Brady M511 printer
Tests fundamental Bluetooth Low Energy connection before implementing full protocol
"""

import asyncio
import logging
from bleak import BleakScanner, BleakClient

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Protocol Constants
APOLLO_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"

async def scan_for_printers():
    """Scan for Brady M511 printers"""
    print("🔍 Scanning for Brady M511 printers...")
    
    try:
        devices = await BleakScanner.discover(timeout=10.0)
        
        brady_printers = []
        for device in devices:
            if device.name and "M511" in device.name:
                brady_printers.append(device)
                print(f"✅ Found Brady M511: {device.name} ({device.address}) RSSI: {getattr(device, 'rssi', 'N/A')}")
        
        if not brady_printers:
            print("❌ No Brady M511 printers found")
            print("\n📋 All discovered devices:")
            for device in devices:
                if device.name:
                    print(f"  - {device.name} ({device.address})")
        
        return brady_printers
        
    except Exception as e:
        print(f"❌ Scan error: {e}")
        return []

async def test_gatt_connection(device):
    """Test basic GATT connection to Brady M511"""
    print(f"\n🔌 Testing GATT connection to {device.name} ({device.address})...")
    
    client = None
    try:
        # Create client with extended timeout
        client = BleakClient(device.address, timeout=20.0)
        
        print("  ⏳ Connecting...")
        await client.connect()
        
        if client.is_connected:
            print("  ✅ GATT connection successful!")
            
            # Discover services
            print("  🔍 Discovering services...")
            services = client.services
            
            print(f"  📋 Found {len(services)} services:")
            brady_service_found = False
            
            for service in services:
                service_name = service.uuid
                if str(service.uuid).lower() == APOLLO_SERVICE_UUID.lower():
                    brady_service_found = True
                    service_name += " (BRADY APOLLO SERVICE ✅)"
                
                print(f"    🔧 Service: {service_name}")
                
                # List characteristics for each service
                for char in service.characteristics:
                    properties = ", ".join(char.properties)
                    print(f"      📡 Characteristic: {char.uuid} ({properties})")
            
            if brady_service_found:
                print("  ✅ Brady APOLLO service found!")
            else:
                print("  ⚠️  Brady APOLLO service NOT found")
                
            # Test reading device info if available
            try:
                device_info_service = client.services.get_service("0000180a-0000-1000-8000-00805f9b34fb")
                if device_info_service:
                    print("  📱 Device Information Service found, attempting to read...")
                    
                    # Try to read manufacturer name
                    try:
                        manufacturer_char = device_info_service.get_characteristic("00002a29-0000-1000-8000-00805f9b34fb")
                        if manufacturer_char:
                            manufacturer = await client.read_gatt_char(manufacturer_char)
                            print(f"    Manufacturer: {manufacturer.decode('utf-8')}")
                    except:
                        pass
                    
                    # Try to read model number
                    try:
                        model_char = device_info_service.get_characteristic("00002a24-0000-1000-8000-00805f9b34fb")
                        if model_char:
                            model = await client.read_gatt_char(model_char)
                            print(f"    Model: {model.decode('utf-8')}")
                    except:
                        pass
                        
            except:
                print("  📱 No Device Information Service available")
            
            return True
            
        else:
            print("  ❌ GATT connection failed - client reports not connected")
            return False
            
    except asyncio.TimeoutError:
        print("  ❌ GATT connection timeout")
        return False
    except Exception as e:
        print(f"  ❌ GATT connection error: {e}")
        return False
    finally:
        if client and client.is_connected:
            print("  🔌 Disconnecting...")
            await client.disconnect()
            print("  ✅ Disconnected")

async def test_specific_address(address):
    """Test connection to a specific Bluetooth address"""
    print(f"\n🎯 Testing specific address: {address}")
    
    # Create a fake device object for testing
    class FakeDevice:
        def __init__(self, address):
            self.address = address
            self.name = f"Test-{address}"
    
    device = FakeDevice(address)
    return await test_gatt_connection(device)

async def main():
    """Main test function"""
    print("🧪 Brady M511 BLE Connection Test")
    print("=" * 50)
    
    # First scan for printers
    printers = await scan_for_printers()
    
    if printers:
        # Test connection to each found printer
        for printer in printers:
            success = await test_gatt_connection(printer)
            if success:
                print(f"✅ Successfully connected to {printer.name}")
            else:
                print(f"❌ Failed to connect to {printer.name}")
    else:
        # Allow manual address entry if no printers found
        print("\n🔧 Manual Testing Mode")
        print("Enter a specific Bluetooth address to test, or press Enter to skip:")
        try:
            manual_address = input("Address (XX:XX:XX:XX:XX:XX): ").strip()
            if manual_address:
                await test_specific_address(manual_address)
        except KeyboardInterrupt:
            print("\n👋 Test interrupted")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")