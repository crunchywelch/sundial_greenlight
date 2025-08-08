#!/usr/bin/env python3
"""
Test just the connection to Brady M511 without sending print jobs
This will help isolate if the issue is connection vs. print job format
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady

BRADY_MAC = "88:8C:19:00:E2:49"

async def test_connection_only():
    """Test just connection and characteristic discovery"""
    print("🧪 Brady M511 Connection Test")
    print("=" * 40)
    
    try:
        print("🔌 Connecting to Brady M511...")
        client, connected = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        if not connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connected successfully")
        print(f"📱 Device name: {client.address}")
        print(f"🔗 Connected: {client.is_connected}")
        
        print("\n🔍 Discovering services and characteristics...")
        
        services = client.services
        service_list = list(services)
        print(f"📋 Found {len(service_list)} services:")
        
        for service in service_list:
            print(f"\n🔷 Service: {service.uuid}")
            print(f"   Characteristics: {len(service.characteristics)}")
            
            for char in service.characteristics:
                properties = []
                if "read" in char.properties:
                    properties.append("read")
                if "write" in char.properties:
                    properties.append("write")
                if "write-without-response" in char.properties:
                    properties.append("write-no-resp")
                if "notify" in char.properties:
                    properties.append("notify")
                if "indicate" in char.properties:
                    properties.append("indicate")
                
                print(f"   📡 {char.uuid} ({', '.join(properties)})")
                
                # Identify key characteristics
                char_uuid = str(char.uuid).lower()
                if "7d9d9a4d" in char_uuid:
                    print("      ⭐ PRINT JOB CHARACTERISTIC")
                elif "a61ae408" in char_uuid:
                    print("      ⭐ PICL REQUEST CHARACTERISTIC") 
                elif "786af345" in char_uuid:
                    print("      ⭐ PICL RESPONSE CHARACTERISTIC")
        
        print(f"\n⏱️  Holding connection for 10 seconds...")
        await asyncio.sleep(10)
        
        await disconnect_from_brady(client)
        print("✅ Disconnected successfully")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(test_connection_only())