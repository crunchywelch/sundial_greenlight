#!/usr/bin/env python3
"""
Debug what's happening in the settings screen Brady connection
"""

import sys
sys.path.insert(0, '.')

def debug_settings_connection():
    """Debug the exact code path the settings screen uses"""
    print("🔧 DEBUG: Settings Screen Brady Connection")
    print("=" * 50)
    
    # Step 1: Test discovery (what settings does first)
    print("\n📍 Step 1: Testing Printer Discovery")
    try:
        from greenlight.hardware.label_printer import discover_brady_printers_sync
        printers = discover_brady_printers_sync()
        
        if not printers:
            print("   ❌ No Brady printers found - this would cause settings to fail")
            return False
            
        printer_info = printers[0]
        print(f"   ✅ Found: {printer_info['name']}")
        print(f"   📍 Address: {printer_info['address']}")
        
    except Exception as e:
        print(f"   ❌ Discovery error: {e}")
        return False
    
    # Step 2: Test centralized connection import (what settings does)
    print(f"\n📦 Step 2: Testing Centralized Connection Import")
    try:
        from greenlight.hardware.brady_connection import test_brady_connection_sync
        print(f"   ✅ Successfully imported test_brady_connection_sync")
        
        # This is the EXACT line from settings screen
        print(f"   🔧 Calling: test_brady_connection_sync('{printer_info['address']}', hold_duration=5.0)")
        
    except Exception as e:
        print(f"   ❌ Import error: {e}")
        return False
    
    # Step 3: Test the actual connection call with debugging
    print(f"\n🔌 Step 3: Testing Connection Call")
    print(f"   📝 This replicates exactly what settings screen does")
    print(f"   🔍 Watch Brady M511 LED - should go SOLID!")
    
    try:
        connection_success = test_brady_connection_sync(printer_info['address'], hold_duration=5.0)
        
        if connection_success:
            print(f"   ✅ Connection successful - LED should have been SOLID")
            print(f"   📝 This means settings screen should work")
        else:
            print(f"   ❌ Connection failed")
            print(f"   📝 This explains why settings screen doesn't work")
            
    except Exception as e:
        print(f"   ❌ Connection call error: {e}")
        print(f"   📝 This is why settings screen fails")
        import traceback
        traceback.print_exc()
        return False
    
    # Step 4: Compare with direct connection
    print(f"\n🆚 Step 4: Compare with Direct Connection")
    
    try:
        import asyncio
        from bleak import BleakClient
        
        async def test_direct():
            client = BleakClient(printer_info['address'], timeout=15.0)
            await client.connect()
            if client.is_connected:
                await asyncio.sleep(3)
                await client.disconnect()
                return True
            return False
        
        # Test direct connection
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            direct_success = loop.run_until_complete(test_direct())
        finally:
            loop.close()
        
        if direct_success:
            print(f"   ✅ Direct connection works")
            if not connection_success:
                print(f"   ⚠️  Centralized function failed but direct works - there's a bug in centralized function!")
        else:
            print(f"   ❌ Direct connection also fails - Brady M511 not available")
            
    except Exception as e:
        print(f"   ❌ Direct connection test error: {e}")
    
    print(f"\n" + "=" * 50)
    print("📊 DEBUG RESULTS") 
    print("=" * 50)
    print(f"✅ Discovery: {'SUCCESS' if printers else 'FAILED'}")
    print(f"✅ Import: SUCCESS")  
    print(f"✅ Centralized Connection: {'SUCCESS' if connection_success else 'FAILED'}")
    
    if not connection_success:
        print(f"\n🔧 ISSUE IDENTIFIED:")
        print(f"   The centralized connection function is not working")
        print(f"   Need to debug the brady_connection.py implementation")

if __name__ == "__main__":
    debug_settings_connection()