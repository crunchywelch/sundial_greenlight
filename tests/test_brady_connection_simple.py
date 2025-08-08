#!/usr/bin/env python3
"""
Simple Brady M511 connection test - connect, hold, disconnect
Direct bleak connection test without application integration
"""

import asyncio
import time
from bleak import BleakClient

BRADY_MAC = "88:8C:19:00:E2:49"

async def test_connection():
    """Simple connection test - connect, hold 30 seconds, disconnect"""
    print("🧪 Brady M511 Simple Connection Test")
    print("=" * 50)
    print(f"📡 Connecting to {BRADY_MAC}...")
    
    client = BleakClient(BRADY_MAC, timeout=15.0)
    
    try:
        # Connect
        start_time = time.time()
        await client.connect()
        connection_time = time.time() - start_time
        
        if not client.is_connected:
            print("❌ Connection failed")
            return False
        
        print(f"✅ Connected in {connection_time:.2f} seconds")
        print("👁️  LED should now be SOLID (not blinking)")
        
        # Hold connection
        print("⏳ Holding connection for 30 seconds...")
        for i in range(6):
            if not client.is_connected:
                print("❌ Connection lost!")
                return False
            print(f"   {30 - i*5}s remaining...")
            await asyncio.sleep(5)
        
        print("✅ Connection held successfully")
        return True
        
    except asyncio.TimeoutError:
        print("❌ Connection timeout")
        return False
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False
    finally:
        if client.is_connected:
            print("🔌 Disconnecting...")
            await client.disconnect()
            print("✅ Disconnected - LED should return to blinking")

async def main():
    success = await test_connection()
    print(f"\n{'✅ SUCCESS' if success else '❌ FAILED'}")

if __name__ == "__main__":
    asyncio.run(main())