#!/usr/bin/env python3
"""
Test script optimized for Wireshark capture analysis
Includes detailed logging and timing for easier packet correlation
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from greenlight.hardware.label_printer import BradyM511Printer
from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady

BRADY_MAC = "88:8C:19:00:E2:49"

async def send_print_job_with_logging(text_to_print: str):
    """Send print job with detailed logging for Wireshark correlation"""
    
    print(f"🧪 WIRESHARK CAPTURE TEST")
    print("=" * 50)
    print(f"⏰ Start time: {time.strftime('%H:%M:%S')}")
    print(f"📝 Text: '{text_to_print}'")
    print(f"🏷️  Label: M4C-375-342 (87x79 pixels)")
    print()
    
    try:
        # STEP 1: Connection
        print("🔌 [STEP 1] Connecting to Brady M511...")
        print(f"   ⏰ Connect start: {time.strftime('%H:%M:%S.%f')[:-3]}")
        
        client, connected = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        if not connected:
            print("❌ Connection failed")
            return False
        
        print(f"   ✅ Connected at: {time.strftime('%H:%M:%S.%f')[:-3]}")
        
        # STEP 2: Find characteristics  
        print("\n🔍 [STEP 2] Finding characteristics...")
        printer = BradyM511Printer(BRADY_MAC)
        printer.ble_client = client
        printer.connected = True
        
        services = client.services
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                for char in service.characteristics:
                    char_uuid = str(char.uuid).lower()
                    if "7d9d9a4d" in char_uuid:  # Print job characteristic
                        printer.print_job_char = char
                        print(f"   ✅ Print job char: {char.uuid}")
                        print(f"   📋 Properties: {list(char.properties)}")
                        break
                if printer.print_job_char:
                    break
        
        if not printer.print_job_char:
            print("❌ Print job characteristic not found")
            await disconnect_from_brady(client)
            return False
        
        # STEP 3: Generate PICL packet
        print(f"\n📦 [STEP 3] Generating PICL packet...")
        print(f"   ⏰ Generate start: {time.strftime('%H:%M:%S.%f')[:-3]}")
        
        picl_data = printer._create_picl_print_job(text_to_print)
        
        print(f"   ✅ PICL packet ready: {len(picl_data)} bytes")
        print(f"   🔍 First 32 bytes: {' '.join(f'{b:02x}' for b in picl_data[:32])}")
        print(f"   🔍 Last 16 bytes: {' '.join(f'{b:02x}' for b in picl_data[-16:])}")
        
        # STEP 4: Send to printer
        print(f"\n📡 [STEP 4] Sending to printer...")
        print(f"   ⏰ Send start: {time.strftime('%H:%M:%S.%f')[:-3]}")
        
        chunk_size = 20
        total_chunks = (len(picl_data) + chunk_size - 1) // chunk_size
        
        print(f"   📊 Transmission: {len(picl_data)} bytes in {total_chunks} chunks of {chunk_size} bytes")
        
        for i in range(0, len(picl_data), chunk_size):
            chunk = picl_data[i:i + chunk_size]
            chunk_num = i // chunk_size + 1
            
            print(f"   📤 Chunk {chunk_num:2d}/{total_chunks}: {len(chunk):2d} bytes - {' '.join(f'{b:02x}' for b in chunk)}")
            
            # Send chunk
            await client.write_gatt_char(printer.print_job_char, chunk, response=False)
            
            # Small delay between chunks
            await asyncio.sleep(0.05)
        
        print(f"   ✅ Send complete: {time.strftime('%H:%M:%S.%f')[:-3]}")
        
        # STEP 5: Wait for processing
        print(f"\n⏳ [STEP 5] Waiting for print job processing...")
        await asyncio.sleep(5)
        
        # STEP 6: Disconnect
        print(f"\n🔌 [STEP 6] Disconnecting...")
        print(f"   ⏰ Disconnect: {time.strftime('%H:%M:%S.%f')[:-3]}")
        
        await disconnect_from_brady(client)
        
        print(f"   ✅ Disconnected: {time.strftime('%H:%M:%S.%f')[:-3]}")
        print(f"\n⏰ Test end time: {time.strftime('%H:%M:%S')}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function for capture test"""
    text = sys.argv[1] if len(sys.argv) > 1 else "CAPTURE1"
    
    print("🎬 READY FOR WIRESHARK CAPTURE")
    print("=" * 40)
    print("1. Start Wireshark capture on Bluetooth interface")
    print("2. Press ENTER when ready to begin test")
    print("3. Look for Brady M511 MAC: 88:8C:19:00:E2:49")
    print()
    
    input("Press ENTER to start test...")
    
    try:
        success = asyncio.run(send_print_job_with_logging(text))
        
        if success:
            print("\n✅ Test completed - check Wireshark capture!")
            print("📊 Look for:")
            print("   - Connection establishment")
            print("   - Service/characteristic discovery") 
            print("   - Write commands to 7d9d9a4d-b530-4d13-8d61-e0ff445add19")
            print("   - PICL packet data in chunks")
        else:
            print("\n❌ Test failed - but capture may still show useful data")
            
    except KeyboardInterrupt:
        print("\n⏹️  Test interrupted")

if __name__ == "__main__":
    main()