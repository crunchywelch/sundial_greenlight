#!/usr/bin/env python3
"""
Test script to match the exact working capture format
Based on analysis of working print.pcapng data
"""

import asyncio
import sys
import os

# Add the parent directory to the path to import greenlight modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady

BRADY_MAC = "88:8C:19:00:E2:49"

def create_working_format_print_job(text: str) -> bytes:
    """
    Create print job matching EXACTLY the working capture format
    
    Working capture analysis shows:
    - Packet 1: 01 01 00 84 00 00 ff 0f 59 35 00 81 02 11 ab 00 00 ff 04...
    - Packet 2: 01 02 00 01 81 06 10 84 0e 85 0e 84 00 00 ff 01...
    """
    
    print(f"🔧 Creating print job matching working capture format for '{text}'")
    
    # This is the EXACT working capture data from print.pcapng
    # Working packet 1 (151 bytes)
    working_packet_1 = bytes.fromhex(
        "010100840000ff0f593500810211ab0000ff04810611840e840d840000ff13"
        "8104118421840000ff058102118459610081021a82810417851187810416860f"
        "8b810415870e8d810414880d8f810413890c91810412890d91810612870e8703"
        "87810611860f860785810611851085098481061085108609858106108510850a"
        "858106108410850c840000ff01810610840f850d840000ff"
    )
    
    # Working packet 2 (151 bytes) 
    working_packet_2 = bytes.fromhex(
        "01020001810610840e850e840000ff01810610840d860e84810610840d850e85"
        "810610840c850f85810610850b850e85810610850a850e868106118508860d86"
        "8106118606860c888106118901880b88810412920c88810413900d8781041381"
        "0f0e858104148d0f848104168a108181021984598b00810238840000ff0e8102"
        "11ab0000ff05810238840000ff0e59b200ffff0d02610247"
    )
    
    print(f"📦 Working packet 1: {len(working_packet_1)} bytes")
    print(f"📦 Working packet 2: {len(working_packet_2)} bytes")
    
    # For now, just return the first working packet to test
    return working_packet_1

async def send_working_format_test(text_to_print: str):
    """Send the exact working format to Brady M511"""
    
    print(f"🖨️  Brady M511 Working Format Test")
    print("=" * 50)
    print(f"📝 Text: '{text_to_print}' (using working capture data)")
    print()
    
    try:
        # Step 1: Connect to Brady M511
        print("🔌 Connecting to Brady M511...")
        client, connected = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        if not connected:
            print("❌ Failed to connect to Brady M511")
            return False
        
        print("✅ Connected to Brady M511")
        
        # Step 2: Find print job characteristic
        print("🔍 Finding print job characteristic...")
        print_job_char = None
        
        services = client.services
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                for char in service.characteristics:
                    char_uuid = str(char.uuid).lower()
                    if "7d9d9a4d" in char_uuid:  # Print job characteristic
                        print_job_char = char
                        print("✅ Found print job characteristic")
                        break
                if print_job_char:
                    break
        
        if not print_job_char:
            print("❌ Could not find print job characteristic")
            await disconnect_from_brady(client)
            return False
        
        # Step 3: Create working format print job
        print(f"📦 Creating working format print job...")
        print_data = create_working_format_print_job(text_to_print)
        print(f"   📏 Print job size: {len(print_data)} bytes")
        print(f"   🔍 First 30 bytes: {' '.join(f'{b:02x}' for b in print_data[:30])}")
        
        # Step 4: Send working format data
        print("📡 Sending working format data to Brady M511...")
        
        # Send in chunks matching the working capture approach
        chunk_size = 20  # Conservative BLE chunk size
        total_chunks = (len(print_data) + chunk_size - 1) // chunk_size
        
        print(f"   Transmitting {len(print_data)} bytes in {total_chunks} chunks...")
        
        for i in range(0, len(print_data), chunk_size):
            chunk = print_data[i:i + chunk_size]
            await client.write_gatt_char(print_job_char, chunk, response=False)
            
            chunk_num = i // chunk_size + 1
            if chunk_num % 10 == 0 or chunk_num == total_chunks:
                print(f"   📊 Progress: {chunk_num}/{total_chunks} chunks")
        
        print("✅ Working format data sent successfully!")
        print()
        print("👁️  **Check your Brady M511 printer**")
        print("   - Should print if format is correct")
        print("   - This uses the EXACT working capture data")
        
        # Wait for processing
        print("\n⏳ Waiting 10 seconds for print job to process...")
        await asyncio.sleep(10)
        
        # Disconnect
        await disconnect_from_brady(client)
        print("🔌 Disconnected from Brady M511")
        
        return True
        
    except Exception as e:
        print(f"❌ Working format test failed: {e}")
        
        # Try to disconnect
        try:
            if 'client' in locals() and client:
                await disconnect_from_brady(client)
        except:
            pass
        
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    text_to_print = input("Enter text (working capture format test): ").strip() or "WORKING"
    
    # Run the test
    try:
        success = asyncio.run(send_working_format_test(text_to_print))
        
        if success:
            print("\n🎉 Working format test completed!")
            print("🔍 If a label printed, we've identified the correct format")
            print("🔍 If no label printed, there may be other factors involved")
        else:
            print("\n💥 Working format test failed!")
            
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")

if __name__ == "__main__":
    main()