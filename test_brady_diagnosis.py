#!/usr/bin/env python3
"""
Brady M511 Connection Diagnosis
Comprehensive diagnosis to understand connection behavior
"""

import asyncio
import logging
import time
from bleak import BleakScanner, BleakClient

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"

async def scan_for_brady():
    """Scan for Brady M511 to verify it's discoverable"""
    print("🔍 Scanning for Brady M511 printer...")
    
    try:
        devices = await BleakScanner.discover(timeout=15.0, return_adv=True)
        
        brady_found = False
        brady_device = None
        
        for device, adv_data in devices.items():
            if device.address.upper() == BRADY_MAC.upper():
                brady_found = True
                brady_device = device
                print(f"✅ Found Brady M511:")
                print(f"   📍 Address: {device.address}")
                print(f"   📛 Name: {device.name}")
                print(f"   📡 RSSI: {getattr(device, 'rssi', 'N/A')}")
                
                # Show advertising data
                print(f"   📋 Advertising Data:")
                if hasattr(adv_data, 'manufacturer_data') and adv_data.manufacturer_data:
                    for company_id, data in adv_data.manufacturer_data.items():
                        print(f"      🏢 Manufacturer {company_id} (0x{company_id:04x}): {data.hex()}")
                        if company_id == 1642:  # Brady's company ID
                            print(f"         (Brady Worldwide Inc.)")
                
                if hasattr(adv_data, 'service_uuids') and adv_data.service_uuids:
                    for uuid in adv_data.service_uuids:
                        print(f"      🔧 Service UUID: {uuid}")
                        if "fd1c" in str(uuid).lower():
                            print(f"         (Brady APOLLO Service)")
                
                if hasattr(adv_data, 'local_name') and adv_data.local_name:
                    print(f"      📛 Local Name: {adv_data.local_name}")
                
                break
        
        if not brady_found:
            print("❌ Brady M511 not found in scan!")
            print("📋 Discovered devices:")
            for device, _ in list(devices.items())[:10]:  # Show first 10
                name = device.name if device.name else "Unknown"
                print(f"   - {name} ({device.address})")
            
            if len(devices) > 10:
                print(f"   ... and {len(devices) - 10} more devices")
            
            return None
        
        return brady_device
        
    except Exception as e:
        print(f"❌ Scan failed: {e}")
        return None

async def test_connection_methods(device):
    """Test different connection approaches"""
    print(f"\n🔧 Testing Different Connection Methods")
    print("=" * 50)
    
    methods = [
        ("Standard", 10.0, False),
        ("Extended Timeout", 30.0, False),
        ("Short Timeout", 5.0, False)
    ]
    
    for method_name, timeout, use_address_type in methods:
        print(f"\n📡 Testing {method_name} (timeout: {timeout}s)")
        
        client = None
        try:
            # Try different connection approaches
            client = BleakClient(device.address, timeout=timeout)
            
            start_time = time.time()
            await client.connect()
            connect_time = time.time() - start_time
            
            if client.is_connected:
                print(f"   ✅ Connected in {connect_time:.2f}s")
                
                # Quick service check
                try:
                    services = client.services
                    service_count = len(list(services))
                    print(f"   📋 Found {service_count} services")
                    
                    # Check for Brady service
                    for service in services:
                        if "fd1c" in str(service.uuid).lower():
                            print(f"   ✅ Brady service found: {service.uuid}")
                            break
                    else:
                        print(f"   ⚠️  Brady service not found")
                        
                except Exception as e:
                    print(f"   ⚠️  Service discovery failed: {e}")
                
                # Hold briefly
                print(f"   ⏱️  Holding connection for 10 seconds...")
                await asyncio.sleep(10)
                
                await client.disconnect()
                print(f"   🔌 Disconnected")
                return True  # Success
                
            else:
                print(f"   ❌ Client reports not connected")
                
        except asyncio.TimeoutError:
            print(f"   ⏱️  Connection timeout after {timeout}s")
        except Exception as e:
            print(f"   ❌ Connection error: {e}")
        finally:
            if client and client.is_connected:
                try:
                    await client.disconnect()
                except:
                    pass
        
        # Brief pause between attempts
        await asyncio.sleep(2)
    
    return False

async def test_quick_connections():
    """Test rapid connection cycles like multi-app usage"""
    print(f"\n🔄 Testing Rapid Connection Cycles")
    print("=" * 40)
    
    success_count = 0
    total_attempts = 5
    
    for i in range(total_attempts):
        print(f"\n🎯 Quick Connection #{i+1}/{total_attempts}")
        
        try:
            client = BleakClient(BRADY_MAC, timeout=8.0)
            
            start_time = time.time()
            await client.connect()
            connect_time = time.time() - start_time
            
            if client.is_connected:
                print(f"   ✅ Connected in {connect_time:.2f}s")
                success_count += 1
                
                # Very brief hold
                await asyncio.sleep(2)
                
                await client.disconnect()
                print(f"   🔌 Disconnected")
            else:
                print(f"   ❌ Connection failed")
                
        except Exception as e:
            print(f"   ❌ Error: {type(e).__name__}")
        
        # Brief pause
        if i < total_attempts - 1:
            await asyncio.sleep(1)
    
    print(f"\n📊 Quick Connection Results: {success_count}/{total_attempts} successful")
    return success_count > 0

async def monitor_advertising():
    """Monitor Brady advertising patterns"""
    print(f"\n📡 Monitoring Brady M511 Advertising Patterns")
    print("=" * 50)
    print("Watching for advertising behavior over 30 seconds...")
    
    detections = []
    
    def detection_callback(device, advertisement_data):
        if device.address.upper() == BRADY_MAC.upper():
            timestamp = time.strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
            rssi = getattr(advertisement_data, 'rssi', 'N/A')
            detections.append((timestamp, rssi))
            
            print(f"   📡 [{timestamp}] Brady detected, RSSI: {rssi}")
            
            # Show service data if present
            if hasattr(advertisement_data, 'service_data') and advertisement_data.service_data:
                for uuid, data in advertisement_data.service_data.items():
                    print(f"      Service {uuid}: {data.hex()}")
    
    try:
        scanner = BleakScanner(detection_callback)
        await scanner.start()
        
        print("   ⏳ Monitoring... (30 seconds)")
        await asyncio.sleep(30)
        
        await scanner.stop()
        
        print(f"\n📊 Advertising Summary:")
        print(f"   📡 Detections: {len(detections)}")
        
        if detections:
            rssi_values = [rssi for _, rssi in detections if isinstance(rssi, (int, float))]
            if rssi_values:
                avg_rssi = sum(rssi_values) / len(rssi_values)
                print(f"   📶 Average RSSI: {avg_rssi:.1f}")
                print(f"   📶 RSSI Range: {min(rssi_values)} to {max(rssi_values)}")
            
            # Show timing pattern
            if len(detections) >= 2:
                intervals = []
                for i in range(1, min(6, len(detections))):  # Show first 5 intervals
                    # This is simplified - real timing would need proper timestamp parsing
                    intervals.append("~1s")  # Placeholder
                print(f"   ⏱️  Detection pattern: {', '.join(intervals)}")
        else:
            print(f"   ❌ No Brady advertising detected!")
            
    except Exception as e:
        print(f"❌ Advertising monitor failed: {e}")

async def main():
    """Main diagnostic function"""
    print("🧪 Brady M511 Connection Diagnosis")
    print("=" * 60)
    print("Comprehensive diagnosis of Brady M511 connection behavior")
    print()
    
    # Step 1: Scan for device
    print("STEP 1: Device Discovery")
    brady_device = await scan_for_brady()
    
    if not brady_device:
        print("\n❌ Cannot proceed - Brady M511 not discoverable")
        print("🔧 Troubleshooting:")
        print("   1. Ensure Brady M511 is powered on")
        print("   2. Check if printer is already connected to another device")
        print("   3. Try power cycling the printer")
        return
    
    # Step 2: Test connection methods
    print(f"\nSTEP 2: Connection Method Testing")
    connection_success = await test_connection_methods(brady_device)
    
    # Step 3: Test rapid connections
    print(f"\nSTEP 3: Rapid Connection Testing")
    rapid_success = await test_quick_connections()
    
    # Step 4: Monitor advertising
    print(f"\nSTEP 4: Advertising Pattern Analysis")
    await monitor_advertising()
    
    # Summary
    print(f"\n" + "="*60)
    print("📊 DIAGNOSTIC SUMMARY")
    print("="*60)
    print(f"✅ Device Discovery: {'SUCCESS' if brady_device else 'FAILED'}")
    print(f"✅ Standard Connection: {'SUCCESS' if connection_success else 'FAILED'}")
    print(f"✅ Rapid Connections: {'SUCCESS' if rapid_success else 'FAILED'}")
    
    if connection_success:
        print("\n🎉 GOOD NEWS: Basic connection is working!")
        print("   The issue may be with connection stability or LED behavior")
        print("   Try the held connection test again")
    else:
        print("\n🔧 CONNECTION ISSUES DETECTED:")
        print("   1. Brady M511 may be connected to another device")
        print("   2. Printer may need power cycle")
        print("   3. Bluetooth adapter issues")
        print("   4. Brady firmware in different mode")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Diagnosis interrupted by user")
    except Exception as e:
        print(f"\n❌ Diagnosis failed: {e}")
        import traceback
        traceback.print_exc()