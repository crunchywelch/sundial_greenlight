#!/usr/bin/env python3
"""
Test different connection modes for Brady M511's multi-app design
"""

import asyncio
import logging
import traceback
import time
from bleak import BleakClient, BleakScanner

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"

async def test_rapid_connection():
    """Test rapid connection attempt - similar to Android timing"""
    print("🚀 Testing rapid connection (like Android ~1 second)...")
    
    try:
        client = BleakClient(BRADY_MAC, timeout=5.0)  # Short timeout like Android
        start_time = time.time()
        
        await client.connect()
        
        if client.is_connected:
            connection_time = time.time() - start_time
            print(f"  ✅ Rapid connection successful in {connection_time:.3f} seconds!")
            
            # Quick service check
            services = client.services
            brady_service_found = any("fd1c" in str(s.uuid).lower() for s in services)
            print(f"  📋 Services: {len(services)}, Brady service: {'✅' if brady_service_found else '❌'}")
            
            await client.disconnect()
            return True
        else:
            print("  ❌ Rapid connection failed")
            return False
            
    except Exception as e:
        print(f"  ❌ Rapid connection error: {e}")
        return False

async def test_connection_during_advertising():
    """Test connecting immediately when we see advertising"""
    print("🔍 Testing connection during active advertising...")
    
    print("  ⏳ Scanning for Brady printer advertising...")
    
    connection_attempted = False
    
    def detection_callback(device, advertisement_data):
        nonlocal connection_attempted
        if device.address.upper() == BRADY_MAC and not connection_attempted:
            connection_attempted = True
            print(f"  📡 Brady advertising detected! RSSI: {advertisement_data.rssi}")
            # Schedule immediate connection attempt
            asyncio.create_task(attempt_immediate_connection(device))
    
    async def attempt_immediate_connection(device):
        """Attempt connection immediately upon detection"""
        print("  🚀 Attempting immediate connection...")
        try:
            client = BleakClient(device.address, timeout=3.0)
            await client.connect()
            
            if client.is_connected:
                print("  ✅ Immediate connection successful!")
                
                # Quick verification
                services = client.services
                print(f"  📋 Found {len(services)} services")
                
                await client.disconnect()
                return True
            else:
                print("  ❌ Immediate connection failed")
                return False
                
        except Exception as e:
            print(f"  ❌ Immediate connection error: {e}")
            return False
    
    try:
        # Start scanning with callback
        scanner = BleakScanner(detection_callback)
        await scanner.start()
        
        # Scan for up to 15 seconds
        await asyncio.sleep(15.0)
        await scanner.stop()
        
        if not connection_attempted:
            print("  ⚠️  Brady printer not seen advertising during scan period")
            return False
            
        # Give the connection attempt time to complete
        await asyncio.sleep(2.0)
        return True
        
    except Exception as e:
        print(f"  ❌ Advertising scan error: {e}")
        return False

async def test_multiple_rapid_attempts():
    """Test multiple rapid connection attempts like multi-app usage"""
    print("🔄 Testing multiple rapid attempts (multi-app simulation)...")
    
    for attempt in range(3):
        print(f"  🎯 Attempt {attempt + 1}/3...")
        
        try:
            client = BleakClient(BRADY_MAC, timeout=2.0)  # Very short timeout
            start_time = time.time()
            
            await client.connect()
            
            if client.is_connected:
                connection_time = time.time() - start_time
                print(f"    ✅ Connected in {connection_time:.3f} seconds")
                
                # Hold connection briefly then disconnect (like app usage)
                await asyncio.sleep(0.5)
                await client.disconnect()
                print(f"    🔌 Disconnected")
                
                # Brief pause before next attempt
                await asyncio.sleep(1.0)
                return True
            else:
                print(f"    ❌ Attempt {attempt + 1} failed")
                
        except Exception as e:
            print(f"    ❌ Attempt {attempt + 1} error: {type(e).__name__}")
        
        # Brief pause between attempts
        await asyncio.sleep(0.5)
    
    print("  ❌ All rapid attempts failed")
    return False

async def test_background_scan_and_connect():
    """Test maintaining background scan and connecting when possible"""
    print("🔍 Testing background scan with opportunistic connection...")
    
    successful_connections = 0
    max_attempts = 5
    
    for attempt in range(max_attempts):
        print(f"  🎯 Background attempt {attempt + 1}/{max_attempts}...")
        
        try:
            # Quick scan to see if device is available
            devices = await BleakScanner.discover(timeout=2.0)
            brady_device = None
            
            for device in devices:
                if device.address.upper() == BRADY_MAC:
                    brady_device = device
                    print(f"    📡 Brady found in scan, RSSI: {getattr(device, 'rssi', 'N/A')}")
                    break
            
            if brady_device:
                # Attempt quick connection
                client = BleakClient(brady_device.address, timeout=1.5)
                await client.connect()
                
                if client.is_connected:
                    print(f"    ✅ Background connection {attempt + 1} successful!")
                    successful_connections += 1
                    
                    await asyncio.sleep(0.2)  # Brief hold
                    await client.disconnect()
                else:
                    print(f"    ❌ Background connection {attempt + 1} failed")
            else:
                print(f"    ⚠️  Brady not found in scan {attempt + 1}")
            
        except Exception as e:
            print(f"    ❌ Background attempt {attempt + 1} error: {type(e).__name__}")
        
        # Wait before next attempt
        await asyncio.sleep(2.0)
    
    print(f"  📊 Success rate: {successful_connections}/{max_attempts}")
    return successful_connections > 0

async def main():
    """Main test function"""
    print("🧪 Brady M511 Multi-App Connection Mode Testing")
    print("=" * 60)
    print("Testing different approaches for multi-app printer design")
    print()
    
    tests = [
        ("Rapid Connection", test_rapid_connection),
        ("Connection During Advertising", test_connection_during_advertising), 
        ("Multiple Rapid Attempts", test_multiple_rapid_attempts),
        ("Background Scan & Connect", test_background_scan_and_connect)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n{'='*20} {test_name} {'='*20}")
        try:
            result = await test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} failed with exception: {e}")
            traceback.print_exc()
            results.append((test_name, False))
        
        # Brief pause between tests
        await asyncio.sleep(1.0)
    
    # Summary
    print("\n" + "="*60)
    print("📊 RESULTS SUMMARY")
    print("="*60)
    
    successful_tests = 0
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:<30} {status}")
        if success:
            successful_tests += 1
    
    print(f"\nOverall success rate: {successful_tests}/{len(tests)}")
    
    if successful_tests > 0:
        print("\n🎉 Found working connection method(s) for multi-app Brady M511!")
    else:
        print("\n🔧 No connection methods worked - may need deeper investigation")
        print("Consider:")
        print("  - BlueZ version compatibility")
        print("  - Kernel Bluetooth stack differences")  
        print("  - Android vs Linux BLE implementation differences")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        traceback.print_exc()