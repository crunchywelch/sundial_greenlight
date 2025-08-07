#!/usr/bin/env python3
"""
Test the exact method now used in settings screen
"""

import sys
import asyncio
import time
sys.path.insert(0, '.')

def test_exact_settings_method():
    """Test the exact method now restored in settings screen"""
    print("🧪 Testing EXACT Settings Screen Method")
    print("=" * 50)
    print("📝 This is the direct connection method restored in settings")
    print()
    
    # Step 1: Discovery (same as settings)
    print("📍 Step 1: Discovery")
    try:
        from greenlight.hardware.label_printer import discover_brady_printers_sync
        printers = discover_brady_printers_sync()
        
        if not printers:
            print("   ❌ No Brady printers found")
            return False
            
        printer_info = printers[0]
        print(f"   ✅ Found: {printer_info['name']} at {printer_info['address']}")
        
    except Exception as e:
        print(f"   ❌ Discovery error: {e}")
        return False
    
    # Step 2: EXACT connection method from settings screen
    print(f"\n🔌 Step 2: Direct Connection Test")
    print(f"   📝 This is the EXACT code now in _test_bluetooth_printer()")
    print(f"   🔍 Watch Brady M511 LED - should go SOLID!")
    
    connection_success = False
    error_details = ""
    
    try:
        # Import bleak for direct connection test (EXACT settings code)
        from bleak import BleakClient
        import asyncio
        import time
        
        async def test_direct_connection():
            """Direct connection test - the exact method that was working"""
            client = BleakClient(printer_info['address'], timeout=15.0)
            
            # Simple connection that makes LED go solid
            await client.connect()
            
            if client.is_connected:
                # Hold connection briefly to see LED behavior
                await asyncio.sleep(5)
                await client.disconnect()
                return True
            return False
        
        # Run direct connection test in new event loop (EXACT settings code)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            connection_success = loop.run_until_complete(test_direct_connection())
        finally:
            loop.close()
            
    except Exception as e:
        error_details = str(e)
    
    # Step 3: Results
    print(f"\n📊 Results:")
    print(f"   Connection Success: {connection_success}")
    if error_details:
        print(f"   Error: {error_details}")
    
    if connection_success:
        print(f"   ✅ SUCCESS - LED should have been SOLID for 5 seconds")
        print(f"   📝 Settings screen should work the same way")
    else:
        print(f"   ❌ FAILED - same issue as settings screen")
        
    return connection_success

def troubleshooting_steps():
    """Show troubleshooting steps for Brady M511"""
    print(f"\n🔧 BRADY M511 TROUBLESHOOTING:")
    print("=" * 40)
    print("1. 🔌 Power Cycle:")
    print("   - Turn Brady M511 OFF")
    print("   - Wait 5 seconds")
    print("   - Turn Brady M511 ON")
    print("   - Wait for LED to start blinking (pairing mode)")
    print()
    print("2. 📱 Check Other Connections:")
    print("   - Close Brady Workstation if open")
    print("   - Close any Brady mobile apps")
    print("   - Make sure no other devices are connected")
    print()
    print("3. 🔵 Verify Pairing Mode:")
    print("   - LED should be blinking blue/cycling")
    print("   - If LED is solid, printer may be connected elsewhere")
    print()
    print("4. 📍 Check Range:")
    print("   - Ensure Brady M511 is within 10 feet")
    print("   - Remove any interference (WiFi routers, etc.)")
    print()
    print("🎯 When working correctly:")
    print("   - LED blinks BEFORE connection")
    print("   - LED goes SOLID during connection")
    print("   - LED returns to blinking after disconnect")

def main():
    """Main test function"""
    
    success = test_exact_settings_method()
    
    print(f"\n" + "=" * 50)
    print("📊 EXACT SETTINGS METHOD TEST RESULTS")
    print("=" * 50)
    
    if success:
        print("✅ SUCCESS: Settings screen method works!")
        print("🎉 Brady M511 LED should have gone solid")
        print("📝 Settings screen will work the same way")
    else:
        print("❌ FAILED: Same issue as settings screen")
        print("📝 This means the Brady M511 needs troubleshooting")
        
        troubleshooting_steps()

if __name__ == "__main__":
    main()