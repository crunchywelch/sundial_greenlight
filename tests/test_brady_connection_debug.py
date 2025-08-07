#!/usr/bin/env python3
"""
Debug the centralized brady_connection.py function
"""

import sys
import asyncio
import traceback
sys.path.insert(0, '.')

async def debug_centralized_connection():
    """Debug the centralized connection function step by step"""
    print("🔧 DEBUG: Centralized Brady Connection Function")
    print("=" * 50)
    
    try:
        from greenlight.hardware.brady_connection import connect_to_brady, BRADY_MAC
        
        print(f"📍 Testing connection to: {BRADY_MAC}")
        print(f"🔍 Watch Brady M511 LED during this test")
        
        # Test the async function directly
        client, success = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        print(f"📊 Connection result:")
        print(f"   Client: {client}")
        print(f"   Success: {success}")
        
        if success and client:
            print(f"   ✅ Connection successful!")
            print(f"   👁️  LED should be SOLID now")
            
            # Hold connection
            print(f"   ⏳ Holding for 5 seconds...")
            await asyncio.sleep(5)
            
            # Disconnect
            from greenlight.hardware.brady_connection import disconnect_from_brady
            await disconnect_from_brady(client)
            print(f"   🔌 Disconnected - LED should return to blinking")
            
        else:
            print(f"   ❌ Connection failed")
            
    except Exception as e:
        print(f"❌ Error in centralized connection: {e}")
        traceback.print_exc()

def debug_sync_wrapper():
    """Debug the sync wrapper that settings screen uses"""
    print("\n🔄 DEBUG: Sync Wrapper Function")
    print("=" * 30)
    
    try:
        from greenlight.hardware.brady_connection import test_brady_connection_sync, BRADY_MAC
        
        print(f"📞 Calling test_brady_connection_sync('{BRADY_MAC}', 5.0)")
        
        result = test_brady_connection_sync(BRADY_MAC, 5.0)
        
        print(f"📊 Sync wrapper result: {result}")
        
        if result:
            print(f"   ✅ Sync wrapper successful")
        else:
            print(f"   ❌ Sync wrapper failed")
            
    except Exception as e:
        print(f"❌ Error in sync wrapper: {e}")
        traceback.print_exc()

async def test_direct_comparison():
    """Test direct BleakClient connection for comparison"""
    print("\n🆚 Direct BleakClient Test (for comparison)")
    print("=" * 40)
    
    try:
        from bleak import BleakClient
        from greenlight.hardware.brady_connection import BRADY_MAC
        
        print(f"🔌 Direct connection to {BRADY_MAC}")
        
        client = BleakClient(BRADY_MAC, timeout=15.0)
        await client.connect()
        
        if client.is_connected:
            print(f"   ✅ Direct connection successful!")
            print(f"   👁️  LED should be SOLID")
            
            await asyncio.sleep(3)
            await client.disconnect()
            print(f"   🔌 Disconnected - LED should return to blinking")
            
            return True
        else:
            print(f"   ❌ Direct connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Direct connection error: {e}")
        return False

async def main():
    """Run all debugging tests"""
    
    # Test 1: Debug centralized async function
    await debug_centralized_connection()
    
    # Test 2: Debug sync wrapper
    debug_sync_wrapper()
    
    # Test 3: Test direct connection for comparison
    direct_works = await test_direct_comparison()
    
    print(f"\n" + "=" * 50)
    print("📊 DEBUGGING SUMMARY")
    print("=" * 50)
    
    if direct_works:
        print("✅ Direct BleakClient connection works")
        print("❌ Centralized function has a bug")
        print()
        print("🔧 ACTION NEEDED:")
        print("   Fix the centralized brady_connection.py implementation")
        print("   The async/sync wrapper may have an issue")
    else:
        print("❌ Both centralized and direct connections fail")
        print("📝 Brady M511 may not be available/powered on")

if __name__ == "__main__":
    asyncio.run(main())