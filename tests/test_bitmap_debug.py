#!/usr/bin/env python3
"""
Debug script to visualize what bitmap is being generated
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from greenlight.hardware.label_printer import BradyM511Printer

def visualize_bitmap(text: str):
    """Generate bitmap and show visual representation"""
    print(f"🔍 Generating bitmap for: '{text}'")
    print("=" * 50)
    
    printer = BradyM511Printer()
    
    # Generate the bitmap data
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # M4C-375-342 label dimensions (from Brady parts database)
        width, height = 87, 79
        print(f"📏 Label size: {width}x{height} pixels")
        
        # Create image with white background
        image = Image.new('1', (width, height), 1)  # 1-bit mode, white=1
        draw = ImageDraw.Draw(image)
        
        # Get font and center text
        font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        x = (width - text_width) // 2
        y = (height - text_height) // 2
        
        print(f"📝 Text size: {text_width}x{text_height} pixels")
        print(f"📍 Text position: ({x}, {y})")
        
        # Draw text
        draw.text((x, y), text, fill=0, font=font)  # 0=black
        
        # Show visual representation
        print("\n🖼️  Visual representation (. = white, # = black):")
        print("   " + "".join(str(i % 10) for i in range(width)))
        
        for row in range(height):
            line = f"{row:2d}|"
            for col in range(width):
                pixel = image.getpixel((col, row))
                line += "#" if pixel == 0 else "."
            print(line)
        
        # Show raw bitmap bytes
        bitmap = []
        for y in range(height):
            bytes_per_row = (width + 7) // 8  # Round up to handle partial bytes  
            for byte_col in range(bytes_per_row):
                row_byte = 0
                for bit in range(8):  # 8 bits per byte
                    x = byte_col * 8 + bit
                    if x < width:
                        pixel = image.getpixel((x, y))
                        if pixel == 0:  # Black pixel
                            row_byte |= (0x80 >> bit)
                bitmap.append(row_byte)
        
        print(f"\n🔢 Raw bitmap data ({len(bitmap)} bytes):")
        for i in range(0, len(bitmap), 16):
            row_bytes = bitmap[i:i+16]
            hex_str = " ".join(f"{b:02x}" for b in row_bytes)
            print(f"   {i:3d}: {hex_str}")
        
        # Test compression
        compressed = printer._compress_bitmap(bitmap)
        print(f"\n🗜️  Compressed size: {len(compressed)} bytes")
        print(f"   First 20 bytes: {' '.join(f'{b:02x}' for b in compressed[:20])}")
        
    except ImportError:
        print("❌ PIL not available for bitmap generation")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_texts = ["TEST123", "HELLO", "A", "12345678"]
    
    for text in test_texts:
        visualize_bitmap(text)
        print("\n" + "=" * 70 + "\n")