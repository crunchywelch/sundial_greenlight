#!/usr/bin/env python3
"""
Simple test script to send a PICL print job to Brady M511
Usage: python test_send_print_job.py [text_to_print]
"""

import asyncio
import sys
import os

# Add the parent directory to the path to import greenlight modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from greenlight.hardware.label_printer import BradyM511Printer
from greenlight.hardware.brady_connection import connect_to_brady, disconnect_from_brady

BRADY_MAC = "88:8C:19:00:E2:49"

async def send_print_job(text_to_print: str):
    """Send a PICL print job to Brady M511"""
    
    print(f"🖨️  Brady M511 Print Job Test")
    print("=" * 50)
    print(f"📝 Text to print: '{text_to_print}'")
    print(f"🏷️  Label type: M4C-375-342")
    print()
    
    try:
        # Step 1: Connect to Brady M511
        print("🔌 Connecting to Brady M511...")
        client, connected = await connect_to_brady(BRADY_MAC, timeout=15.0)
        
        if not connected:
            print("❌ Failed to connect to Brady M511")
            print("   - Check if printer is on and in range")
            print("   - Verify MAC address is correct")
            return False
        
        print("✅ Connected to Brady M511")
        
        # Step 2: Create printer instance and find characteristics
        print("🔍 Finding print job characteristic...")
        printer = BradyM511Printer(BRADY_MAC)
        printer.ble_client = client
        printer.connected = True
        
        # Find the print job characteristic
        services = client.services
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                for char in service.characteristics:
                    char_uuid = str(char.uuid).lower()
                    if "7d9d9a4d" in char_uuid:  # Print job characteristic
                        printer.print_job_char = char
                        print("✅ Found print job characteristic")
                        break
                if printer.print_job_char:
                    break
        
        if not printer.print_job_char:
            print("❌ Could not find print job characteristic")
            await disconnect_from_brady(client)
            return False
        
        # Step 3: Generate raw binary print job
        print(f"📦 Creating raw binary print job for '{text_to_print}'...")
        print_data = printer._create_simple_print_job(text_to_print)
        print(f"   📏 Print job size: {len(print_data)} bytes")
        
        # Step 4: Send raw binary print job to Brady M511
        print("📡 Sending print job to Brady M511...")
        
        # Send in chunks (Brady BLE has MTU limits)  
        chunk_size = 20  # Conservative chunk size for BLE
        total_chunks = (len(print_data) + chunk_size - 1) // chunk_size
        
        print(f"   Transmitting {len(print_data)} bytes in {total_chunks} chunks...")
        
        for i in range(0, len(print_data), chunk_size):
            chunk = print_data[i:i + chunk_size]
            await client.write_gatt_char(printer.print_job_char, chunk, response=False)
            
            # Show progress every 25 chunks
            chunk_num = i // chunk_size + 1
            if chunk_num % 25 == 0 or chunk_num == total_chunks:
                print(f"   📊 Progress: {chunk_num}/{total_chunks} chunks")
        
        print("✅ Print job sent successfully!")
        print()
        print("👁️  **Check your Brady M511 printer**")
        print(f"   - Label should print with text: '{text_to_print}'")
        print("   - M4C-375-342 sleeve label (87x79 pixels)")
        print("   - Text should be centered on the label")
        
        # Wait for print job to process
        print("\n⏳ Waiting 5 seconds for print job to process...")
        await asyncio.sleep(5)
        
        # Step 5: Disconnect
        await disconnect_from_brady(client)
        print("🔌 Disconnected from Brady M511")
        
        return True
        
    except Exception as e:
        print(f"❌ Print job failed: {e}")
        print("\nTroubleshooting:")
        print("- Ensure Brady M511 is powered on")
        print("- Check M4C-375-342 labels are loaded")
        print("- Verify printer is not in use by other apps")
        print("- Try restarting the Brady M511")
        
        # Try to disconnect if we have a connection
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
    # Get text to print from command line or prompt user
    if len(sys.argv) > 1:
        text_to_print = sys.argv[1]
    else:
        text_to_print = input("Enter text to print (max 12 characters): ").strip()
    
    if not text_to_print:
        print("❌ No text provided")
        return
    
    if len(text_to_print) > 12:
        print(f"⚠️  Text truncated to 12 characters: '{text_to_print[:12]}'")
        text_to_print = text_to_print[:12]
    
    # Run the print job
    try:
        success = asyncio.run(send_print_job(text_to_print))
        
        if success:
            print("\n🎉 Print job completed successfully!")
        else:
            print("\n💥 Print job failed!")
            
    except KeyboardInterrupt:
        print("\n⏹️  Print job interrupted by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")

if __name__ == "__main__":
    main()