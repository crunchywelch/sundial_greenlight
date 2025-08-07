#!/usr/bin/env python3
"""
Test Brady connection in a truly synchronous context (like settings screen)
"""

import sys
sys.path.insert(0, '.')

def test_in_sync_context():
    """Test Brady connection in pure sync context"""
    print("🧪 Testing Brady Connection in Sync Context")
    print("=" * 50)
    print("📝 This replicates the settings screen environment")
    print()
    
    # Step 1: Discovery
    print("📍 Step 1: Printer Discovery")
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
    
    # Step 2: Connection test using centralized function
    print(f"\n🔌 Step 2: Centralized Connection Test")
    print(f"   📝 This is what settings screen now calls")
    print(f"   🔍 Watch Brady M511 LED - should go SOLID during connection!")
    
    try:
        from greenlight.hardware.brady_connection import test_brady_connection_sync
        
        # This is the EXACT call settings screen makes
        connection_success = test_brady_connection_sync(printer_info['address'], hold_duration=5.0)
        
        if connection_success:
            print(f"   ✅ Connection test SUCCESSFUL!")
            print(f"   👁️  LED should have been SOLID for 5 seconds")
            print(f"   📝 Settings screen should work now!")
        else:
            print(f"   ❌ Connection test failed")
            print(f"   📝 Brady M511 may not be available")
            
        return connection_success
        
    except Exception as e:
        print(f"   ❌ Connection test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function - pure sync context"""
    
    success = test_in_sync_context()
    
    print(f"\n" + "=" * 50)
    print("📊 SYNC CONTEXT TEST RESULTS")
    print("=" * 50)
    
    if success:
        print("✅ SUCCESS: Brady connection works in sync context!")
        print("🎉 Settings screen should now work correctly")
        print("👁️  LED behavior should be consistent")
        print()
        print("📝 Next steps:")
        print("   1. Test the actual settings screen")
        print("   2. Verify LED goes solid during connection")
        print("   3. Brady connection is now centralized!")
    else:
        print("❌ Connection failed")
        print("📝 This could be because:")
        print("   1. Brady M511 is not powered on")
        print("   2. Brady M511 is connected to another device")
        print("   3. Brady M511 is out of range")
        print()
        print("🔧 Try:")
        print("   1. Power cycle Brady M511")
        print("   2. Make sure no other apps are connected")
        print("   3. Run test again")

if __name__ == "__main__":
    # Pure sync context - no asyncio.run()
    main()