#!/usr/bin/env python3
"""
Brady M511 Print Job Generator
Creates proper print jobs for Brady M511 based on reverse engineering analysis
"""

import asyncio
import logging
import uuid
import struct
from typing import Optional
from bleak import BleakClient
from PIL import Image, ImageDraw, ImageFont
import io

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"
PICL_REQUEST_CHAR_UUID = "a61ae408-3273-420c-a9db-0669f4f23b69"
PICL_RESPONSE_CHAR_UUID = "786af345-1b68-c594-c643-e2867da117e3"

class BradyM511PrintJob:
    """Generate Brady M511 print jobs"""
    
    def __init__(self):
        self.job_id = None
        self.label_type = "M4C-187"  # Default Brady label type from Wireshark
        
    def generate_job_id(self) -> str:
        """Generate unique job ID like in Wireshark capture"""
        # Generate a 32-character hex string like the Android app
        return uuid.uuid4().hex
    
    def create_text_image(self, text: str, width: int = 120, height: int = 30) -> Image.Image:
        """Create a simple text image for printing"""
        # Create white background image
        img = Image.new('RGB', (width, height), 'white')
        draw = ImageDraw.Draw(img)
        
        # Try to use a simple font, fall back to default if not available
        try:
            # Small font for narrow labels
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except:
            font = ImageFont.load_default()
        
        # Calculate text position to center it
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        # Draw black text on white background
        draw.text((x, y), text, fill='black', font=font)
        
        return img
    
    def image_to_brady_bitmap(self, image: Image.Image) -> bytes:
        """Convert image to Brady M511 bitmap format using reverse-engineered process"""
        
        # Convert to grayscale using Brady's formula: 0.3*R + 0.59*G + 0.11*B
        grayscale_img = image.convert('L')
        
        # Apply threshold of 128 (like in bundle.pretty.js)
        threshold = 128
        bw_img = grayscale_img.point(lambda x: 0 if x < threshold else 255, '1')
        
        # Convert to bitmap data
        width, height = bw_img.size
        bitmap_data = bytearray()
        
        # Process row by row (like printMonoOrSpotColorPage function)
        for y in range(height):
            row_bits = []
            for x in range(width):
                pixel = bw_img.getpixel((x, y))
                # 0 = black pixel (print), 1 = white pixel (no print)
                bit = 1 if pixel == 255 else 0
                row_bits.append(bit)
            
            # Pack bits into bytes (8 bits per byte)
            row_bytes = bytearray()
            for i in range(0, len(row_bits), 8):
                byte_bits = row_bits[i:i+8]
                # Pad with 1s (white) if needed
                while len(byte_bits) < 8:
                    byte_bits.append(1)
                
                # Pack bits into byte (MSB first)
                byte_val = 0
                for j, bit in enumerate(byte_bits):
                    if bit:
                        byte_val |= (1 << (7 - j))
                
                row_bytes.append(byte_val)
            
            bitmap_data.extend(row_bytes)
        
        return bytes(bitmap_data)
    
    def simple_rle_compress(self, data: bytes) -> bytes:
        """Simple run-length encoding similar to Brady's compressLine function"""
        if not data:
            return b''
        
        compressed = bytearray()
        current_byte = data[0]
        count = 1
        
        for byte in data[1:]:
            if byte == current_byte and count < 255:
                count += 1
            else:
                # Encode run: count followed by byte value
                compressed.append(count)
                compressed.append(current_byte)
                current_byte = byte
                count = 1
        
        # Don't forget the last run
        compressed.append(count)
        compressed.append(current_byte)
        
        return bytes(compressed)
    
    def create_print_job(self, text: str) -> bytes:
        """Create complete Brady M511 print job based on Wireshark analysis"""
        
        # Generate job ID
        self.job_id = self.generate_job_id()
        
        print_job = bytearray()
        
        # Packet sequence header (from Wireshark: 01 00 00)
        print_job.extend([0x01, 0x00, 0x00])
        
        # Job ID section (from Wireshark analysis)
        job_id_section = f"K\x00\x0a{self.job_id}\x0d"
        print_job.extend([0x02])  # Section type
        print_job.extend([len(job_id_section)])
        print_job.extend(job_id_section.encode('ascii'))
        
        # Label type section
        label_section = f"K\x00\x09{self.label_type}\x0d"
        print_job.extend([0x02])  # Section type  
        print_job.extend([len(label_section)])
        print_job.extend(label_section.encode('ascii'))
        
        # Brady positioning commands (from Wireshark)
        commands = [
            "D+0001",  # Position command
            "C+0001",  # Position command  
            "c\x00",   # Unknown command
            "p+00",    # Position
            "o+00",    # Position
            "O+00",    # Position
            "b+00",    # Position
            "M\x01"    # Mode command
        ]
        
        for cmd in commands:
            print_job.extend([0x02])  # Section type
            print_job.extend([len(cmd)])
            print_job.extend(cmd.encode('ascii'))
        
        # Serial number / content section (like Wireshark: 00820178)
        content_section = f"K\x00\x0c{text[:8].ljust(8, '0')}"  # Pad/truncate to 8 chars
        print_job.extend([0x02])
        print_job.extend([len(content_section)])
        print_job.extend(content_section.encode('ascii'))
        
        # More Brady commands from Wireshark
        more_commands = ["A", "Q", "a"]
        for cmd in more_commands:
            print_job.extend([0x02])
            print_job.extend([len(cmd)])
            print_job.extend(cmd.encode('ascii'))
        
        # Text content section
        text_content = f"IBUlbl0\x0d"  # Brady text format from Wireshark
        print_job.extend([0x02])
        print_job.extend([len(text_content)])
        print_job.extend(text_content.encode('ascii'))
        
        # Image bitmap section
        image = self.create_text_image(text)
        bitmap_data = self.image_to_brady_bitmap(image)
        
        # Add bitmap header (from Wireshark analysis)
        print_job.extend([0x58, 0x00, 0x00])  # X position
        print_job.extend([0x59, 0x00, 0x00])  # Y position  
        print_job.extend([0x59, 0x06, 0x00])  # Image dimensions
        
        # Add compressed bitmap data
        compressed_bitmap = self.simple_rle_compress(bitmap_data)
        
        # Add bitmap data in chunks (like Wireshark pattern)
        chunk_size = 64  # Observed chunk pattern
        for i in range(0, len(compressed_bitmap), chunk_size):
            chunk = compressed_bitmap[i:i+chunk_size]
            print_job.extend([0x81, 0x02])  # Bitmap data header
            print_job.extend([len(chunk)])
            print_job.extend(chunk)
        
        # End markers (from Wireshark)
        print_job.extend([0x84, 0x00, 0x00, 0xFF])  # End of image
        
        print(f"Generated Brady M511 print job: {len(print_job)} bytes")
        print(f"Job ID: {self.job_id}")
        
        return bytes(print_job)

async def test_print_job_generation():
    """Test Brady M511 print job generation and sending"""
    print("🧪 Brady M511 Print Job Test")
    print("=" * 40)
    
    # Create print job
    brady_printer = BradyM511PrintJob()
    test_text = "TEST001"
    print_data = brady_printer.create_print_job(test_text)
    
    print(f"📄 Generated print job for text: '{test_text}'")
    print(f"📦 Print job size: {len(print_data)} bytes")
    print(f"🆔 Job ID: {brady_printer.job_id}")
    
    # Show first 100 bytes
    print(f"📋 First 100 bytes: {print_data[:100].hex()}")
    
    # Try to send to printer
    client = None
    try:
        print(f"\n🔌 Connecting to Brady M511...")
        client = BleakClient(BRADY_MAC, timeout=10.0)
        await client.connect()
        
        if not client.is_connected:
            print("❌ Connection failed")
            return False
        
        print("✅ Connected to Brady M511")
        
        # Get the print job characteristic
        services = client.services
        brady_service = None
        for service in services:
            if "fd1c" in str(service.uuid).lower():
                brady_service = service
                break
        
        if not brady_service:
            print("❌ Brady service not found")
            return False
        
        print_job_char = None
        for char in brady_service.characteristics:
            if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                print_job_char = char
                break
        
        if not print_job_char:
            print("❌ Print job characteristic not found")
            return False
        
        print("📡 Sending print job to Brady M511...")
        
        # Send print job in chunks (like Wireshark shows)
        chunk_size = 150  # Observed from Wireshark
        for i in range(0, len(print_data), chunk_size):
            chunk = print_data[i:i+chunk_size]
            print(f"   Sending chunk {i//chunk_size + 1}: {len(chunk)} bytes")
            await client.write_gatt_char(print_job_char, chunk)
            await asyncio.sleep(0.1)  # Brief pause between chunks
        
        print("✅ Print job sent successfully!")
        print("🖨️  Check the Brady M511 printer for output")
        
        return True
        
    except Exception as e:
        print(f"❌ Print job test failed: {e}")
        return False
    finally:
        if client and client.is_connected:
            print("🔌 Disconnecting...")
            await client.disconnect()

async def main():
    """Main test function"""
    success = await test_print_job_generation()
    
    if success:
        print("\n🎉 Brady M511 print job test completed!")
    else:
        print("\n❌ Print job test failed")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()