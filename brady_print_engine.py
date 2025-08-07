#!/usr/bin/env python3
"""
Brady M511 Print Engine
Complete implementation based on reverse-engineered Brady SDK
Handles image processing, compression, and print job generation
"""

import asyncio
import logging
import uuid
import struct
import zlib
from typing import Optional, List
from bleak import BleakClient
from PIL import Image, ImageDraw, ImageFont
import json

# Try to import LZ4, use zlib fallback if not available
try:
    import lz4.block
    HAS_LZ4 = True
except ImportError:
    HAS_LZ4 = False

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Brady M511 Constants
BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"
PICL_REQUEST_CHAR_UUID = "a61ae408-3273-420c-a9db-0669f4f23b69" 
PICL_RESPONSE_CHAR_UUID = "786af345-1b68-c594-c643-e2867da117e3"

# PICL Protocol Constants
PICL_HEADER_UUID = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
PICL_COMPRESSED_HEADER = bytes([143, 153])  # 0x8F, 0x99

class BradyImageProcessor:
    """Handles image processing using Brady's reverse-engineered algorithm"""
    
    def __init__(self):
        self.label_width_pixels = 120   # M4C-187 label width in pixels at 300 DPI
        self.label_height_pixels = 30   # Approximate height for narrow labels
        
    def create_text_image(self, text: str) -> Image.Image:
        """Create text image optimized for Brady M4C-187 labels"""
        # Create white background
        img = Image.new('RGB', (self.label_width_pixels, self.label_height_pixels), 'white')
        draw = ImageDraw.Draw(img)
        
        # Use small font for narrow labels
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except:
            font = ImageFont.load_default()
        
        # Center text
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = max(0, (self.label_width_pixels - text_width) // 2)
        y = max(0, (self.label_height_pixels - text_height) // 2)
        
        draw.text((x, y), text, fill='black', font=font)
        return img
    
    def process_image_to_bitmap(self, image: Image.Image) -> bytes:
        """Convert image to Brady bitmap format using SDK algorithm"""
        
        # Step 1: Scale to label dimensions
        scaled_img = image.resize((self.label_width_pixels, self.label_height_pixels), Image.LANCZOS)
        
        # Step 2: Convert to grayscale using Brady's formula (0.3*R + 0.59*G + 0.11*B)
        width, height = scaled_img.size
        pixels = scaled_img.load()
        
        grayscale_data = []
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y][:3]  # Handle both RGB and RGBA
                # Brady's grayscale conversion
                gray = int(0.3 * r + 0.59 * g + 0.11 * b)
                grayscale_data.append(gray)
        
        # Step 3: Apply threshold of 128 (Brady's standard)
        bitmap_data = bytearray()
        bits_per_byte = 8
        
        for y in range(height):
            row_bits = []
            for x in range(width):
                pixel_index = y * width + x
                gray_value = grayscale_data[pixel_index]
                # 0 = black pixel (print), 1 = white pixel (no print)  
                bit = 1 if gray_value > 128 else 0
                row_bits.append(bit)
            
            # Pack bits into bytes (MSB first, like Brady SDK)
            for i in range(0, len(row_bits), bits_per_byte):
                byte_bits = row_bits[i:i+bits_per_byte]
                # Pad with white (1) if needed
                while len(byte_bits) < bits_per_byte:
                    byte_bits.append(1)
                
                byte_val = 0
                for j, bit in enumerate(byte_bits):
                    if bit:
                        byte_val |= (1 << (7 - j))
                
                bitmap_data.append(byte_val)
        
        return bytes(bitmap_data)

class BradyPrintJobGenerator:
    """Generates Brady M511 print jobs using reverse-engineered protocol"""
    
    def __init__(self):
        self.image_processor = BradyImageProcessor()
        
    def generate_job_id(self) -> str:
        """Generate 32-character hex job ID like Brady SDK"""
        return uuid.uuid4().hex
    
    def create_picl_packet(self, json_data: dict) -> bytes:
        """Create PICL packet with Brady's exact format"""
        json_string = json.dumps(json_data, separators=(',', ':'))
        payload = json_string.encode('utf-8')
        
        # PICL packet structure: HEADER + LENGTH + PAYLOAD
        length_bytes = struct.pack('<I', len(payload))  # Little-endian 4-byte length
        packet = PICL_HEADER_UUID + length_bytes + payload
        
        return packet
    
    def compress_with_lz4(self, data: bytes) -> bytes:
        """Compress data using LZ4 like Brady SDK, with zlib fallback"""
        if HAS_LZ4:
            try:
                # Use LZ4 block compression (high compression mode)
                compressed = lz4.block.compress(data, mode='high_compression', compression=12)
                return compressed
            except Exception as e:
                logger.warning(f"LZ4 compression failed: {e}, using zlib fallback")
        
        # Use zlib fallback
        logger.info("Using zlib compression (LZ4 not available)")
        return zlib.compress(data, level=9)
    
    def create_compressed_print_job(self, bitmap_data: bytes, job_id: str, text: str) -> bytes:
        """Create compressed print job like Brady SDK class De"""
        
        # Create Brady print commands (reverse-engineered from Wireshark)
        print_commands = []
        
        # Label setup commands
        print_commands.append(f"K\x00\x0a{job_id}\x0d")  # Job ID
        print_commands.append(f"K\x00\x09M4C-187\x0d")   # Label type
        
        # Positioning commands (from Wireshark analysis)
        position_commands = [
            "D+0001",  # Position
            "C+0001",  # Position
            "c\x00",   # Control
            "p+00",    # Position
            "o+00",    # Position  
            "O+00",    # Position
            "b+00",    # Position
            "M\x01"    # Mode
        ]
        print_commands.extend(position_commands)
        
        # Content section
        content_id = text[:8].ljust(8, '0')  # 8-character content ID
        print_commands.append(f"K\x00\x0c{content_id}")
        
        # Additional Brady commands
        print_commands.extend(["A", "Q", "a"])
        
        # Text format command
        print_commands.append(f"IBUlbl0\x0d")
        
        # Build complete command string
        command_string = ''.join(print_commands)
        
        # Add bitmap positioning
        bitmap_commands = bytearray()
        bitmap_commands.extend([0x58, 0x00, 0x00])  # X position
        bitmap_commands.extend([0x59, 0x00, 0x00])  # Y position
        bitmap_commands.extend([0x59, 0x06, 0x00])  # Dimensions
        
        # Simple RLE compression for bitmap (Brady style)
        compressed_bitmap = self._compress_bitmap_rle(bitmap_data)
        
        # Add bitmap data with headers
        bitmap_section = bytearray()
        bitmap_section.extend([0x81, 0x02, 0x38])  # Bitmap header
        bitmap_section.extend(compressed_bitmap[:64])  # First chunk
        bitmap_section.extend([0x84, 0x00, 0x00, 0xFF, 0x0F])  # Continuation
        
        if len(compressed_bitmap) > 64:
            bitmap_section.extend([0x81, 0x02, 0x11, 0xAB])  # Next chunk header
            bitmap_section.extend(compressed_bitmap[64:])
            bitmap_section.extend([0x84, 0x00, 0x00, 0xFF])  # End marker
        
        # Combine all sections
        complete_job = command_string.encode('ascii') + bitmap_commands + bitmap_section
        
        # Create final packet with sequence header (from Wireshark)
        final_packet = bytearray([0x01, 0x00, 0x00])  # Sequence header
        final_packet.extend(complete_job)
        
        return bytes(final_packet)
    
    def _compress_bitmap_rle(self, bitmap_data: bytes) -> bytes:
        """Simple RLE compression for bitmap data"""
        if not bitmap_data:
            return b''
        
        compressed = bytearray()
        current_byte = bitmap_data[0]
        count = 1
        
        for byte in bitmap_data[1:]:
            if byte == current_byte and count < 255:
                count += 1
            else:
                compressed.extend([count, current_byte])
                current_byte = byte
                count = 1
        
        # Add final run
        compressed.extend([count, current_byte])
        return bytes(compressed)
    
    def generate_print_job(self, text: str) -> tuple[bytes, str]:
        """Generate complete Brady M511 print job"""
        
        # Generate unique job ID
        job_id = self.generate_job_id()
        
        # Create and process image
        image = self.image_processor.create_text_image(text)
        bitmap_data = self.image_processor.process_image_to_bitmap(image)
        
        # Create compressed print job
        print_job_data = self.create_compressed_print_job(bitmap_data, job_id, text)
        
        logger.info(f"Generated Brady M511 print job: {len(print_job_data)} bytes")
        logger.info(f"Job ID: {job_id}")
        logger.info(f"Text: '{text}'")
        
        return print_job_data, job_id

class BradyM511PrintEngine:
    """Complete Brady M511 print engine with BLE communication"""
    
    def __init__(self, device_address: str = BRADY_MAC):
        self.device_address = device_address
        self.client = None
        self.print_job_generator = BradyPrintJobGenerator()
        self.connected = False
        
    async def connect(self) -> bool:
        """Connect to Brady M511 printer"""
        try:
            logger.info(f"Connecting to Brady M511 at {self.device_address}")
            self.client = BleakClient(self.device_address, timeout=15.0)
            await self.client.connect()
            
            if not self.client.is_connected:
                logger.error("Failed to connect to Brady M511")
                return False
            
            logger.info("Successfully connected to Brady M511")
            self.connected = True
            return True
            
        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from printer"""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            self.connected = False
            logger.info("Disconnected from Brady M511")
    
    async def print_text(self, text: str) -> bool:
        """Print text label on Brady M511"""
        if not self.connected:
            logger.error("Not connected to printer")
            return False
        
        try:
            # Generate print job
            print_job_data, job_id = self.print_job_generator.generate_print_job(text)
            
            # Get print job characteristic
            services = self.client.services
            brady_service = None
            for service in services:
                if "fd1c" in str(service.uuid).lower():
                    brady_service = service
                    break
            
            if not brady_service:
                logger.error("Brady service not found")
                return False
            
            print_job_char = None
            for char in brady_service.characteristics:
                if str(char.uuid).lower() == PRINT_JOB_CHAR_UUID.lower():
                    print_job_char = char
                    break
            
            if not print_job_char:
                logger.error("Print job characteristic not found") 
                return False
            
            # Send print job in chunks (like Brady SDK)
            chunk_size = 148  # Brady BLE chunk size
            total_chunks = (len(print_job_data) + chunk_size - 1) // chunk_size
            
            logger.info(f"Sending print job in {total_chunks} chunks...")
            
            for i in range(0, len(print_job_data), chunk_size):
                chunk = print_job_data[i:i+chunk_size]
                chunk_num = i // chunk_size + 1
                
                logger.debug(f"Sending chunk {chunk_num}/{total_chunks}: {len(chunk)} bytes")
                await self.client.write_gatt_char(print_job_char, chunk)
                
                # Brief pause between chunks to avoid overwhelming the printer
                await asyncio.sleep(0.05)
            
            logger.info(f"✅ Print job sent successfully! Job ID: {job_id}")
            logger.info("🖨️  Check Brady M511 printer for printed label")
            
            return True
            
        except Exception as e:
            logger.error(f"Print job failed: {e}")
            return False

# Test the complete Brady M511 print engine
async def main():
    """Test the Brady M511 print engine"""
    print("🧪 Brady M511 Print Engine Test")
    print("=" * 50)
    
    # Create print engine
    printer = BradyM511PrintEngine()
    
    try:
        # Connect to printer
        if not await printer.connect():
            print("❌ Failed to connect to Brady M511")
            return
        
        # Print test label
        test_text = "TEST123"
        print(f"🏷️  Printing test label: '{test_text}'")
        
        success = await printer.print_text(test_text)
        
        if success:
            print("✅ Print job completed successfully!")
            print("📄 Check the Brady M511 printer for your printed label")
        else:
            print("❌ Print job failed")
            
    finally:
        await printer.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Test interrupted by user")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()