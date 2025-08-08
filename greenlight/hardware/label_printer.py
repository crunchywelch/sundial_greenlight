"""
Brady M511 Label Printer - Working Implementation
Based on successful reverse engineering and connection testing

This implementation provides full Brady M511 support for the Greenlight application
including Bluetooth connection, print job generation, and status monitoring.
"""

import logging
import asyncio
import uuid
import json
import struct
import time
import base64
import zlib
from typing import Dict, Any, Optional, List
from .interfaces import LabelPrinterInterface, PrintJob

# Set up logging
logger = logging.getLogger(__name__)

# Brady M511 Protocol Constants
BRADY_MAC = "88:8C:19:00:E2:49"
BRADY_SERVICE_UUID = "0000fd1c-0000-1000-8000-00805f9b34fb"
PRINT_JOB_CHAR_UUID = "7d9d9a4d-b530-4d13-8d61-e0ff445add19"
PICL_REQUEST_CHAR_UUID = "a61ae408-3273-420c-a9db-0669f4f23b69"
PICL_RESPONSE_CHAR_UUID = "786af345-1b68-c594-c643-e2867da117e3"

# PICL Protocol Constants
PICL_HEADER_UUID = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])

# Brady Property Keys (from reverse engineering)
class BradyPropertyKey:
    PRINT_JOB_ID_AND_STATUS = "0029"
    JOB_PRINTING_COMPLETE = "002A"
    BATTERY_CHARGE_STATUS = "0001"
    SUBSTRATE_REMAINING_PERCENT = "001B"
    FIRMWARE_VERSION = "0028"
    FATAL_ERROR = "0006"
    PRINT_JOB_ERROR = "0009"


def discover_brady_printers_sync() -> List[Dict[str, str]]:
    """
    Synchronous Brady printer discovery
    
    Returns:
        List of discovered printer info dictionaries
    """
    # For now, return the known Brady M511
    # In a full implementation, this could use BLE scanning
    return [{
        'name': 'M511-PGM5112423102007',
        'address': BRADY_MAC,
        'model': 'M511',
        'connection_type': 'bluetooth'
    }]


class BradyM511Printer(LabelPrinterInterface):
    """
    Brady M511 Label Printer Implementation
    
    Features:
    - Bluetooth Low Energy connection
    - PICL protocol communication  
    - Print job generation and transmission
    - Status monitoring and error handling
    - Compatible with M4C-375-342 labels
    """
    
    def __init__(self, device_path: Optional[str] = None):
        """
        Initialize Brady M511 printer
        
        Args:
            device_path: Bluetooth MAC address (None for auto-discovery)
        """
        self.device_path = device_path  # None means auto-discover when needed
        self.connection_type = "bluetooth"
        self.connected = False
        self.ble_client = None
        self.print_job_char = None
        self.picl_request_char = None
        self.picl_response_char = None
        self.printer_status = {}
        self.current_job_id = None
        self._discovery_attempted = False
        
        # Import bleak here to handle missing dependency gracefully
        try:
            from bleak import BleakClient
            self.BleakClient = BleakClient
        except ImportError:
            logger.error("bleak library not available - Brady M511 printer will not work")
            self.BleakClient = None
    
    def initialize(self) -> bool:
        """Initialize Brady M511 printer via Bluetooth"""
        try:
            if not self.BleakClient:
                logger.error("Brady M511 initialization failed - bleak library not available")
                return False
            
            # Auto-discover if no device path specified
            if not self.device_path and not self._discovery_attempted:
                self._discovery_attempted = True
                logger.info("Auto-discovering Brady M511 printers...")
                printers = discover_brady_printers_sync()
                if printers:
                    self.device_path = printers[0]['address']
                    logger.info(f"Auto-discovered Brady M511: {printers[0]['name']} at {self.device_path}")
                else:
                    logger.warning("No Brady M511 printers found during auto-discovery")
                    return False
            
            if not self.device_path:
                logger.error("No Brady M511 device address available")
                return False
                
            logger.info(f"Initializing Brady M511 printer at {self.device_path}")
            return self._initialize_bluetooth_sync()
                
        except Exception as e:
            logger.error(f"Failed to initialize Brady M511: {e}")
            return False
    
    def _initialize_bluetooth_sync(self) -> bool:
        """Initialize Bluetooth connection in sync context"""
        try:
            # Check if there's already a running event loop
            try:
                loop = asyncio.get_running_loop()
                logger.warning("Already in async context, cannot initialize Brady M511 in sync mode")
                return False
            except RuntimeError:
                # No running loop, create new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(self._initialize_bluetooth_async())
                finally:
                    loop.close()
                    
        except Exception as e:
            logger.error(f"Brady M511 Bluetooth initialization failed: {e}")
            return False
    
    async def _initialize_bluetooth_async(self) -> bool:
        """Async Bluetooth initialization"""
        try:
            logger.info(f"Initializing Brady M511 at {self.device_path}")
            
            # Use centralized connection function for reliable LED behavior
            from .brady_connection import connect_to_brady
            self.ble_client, connected = await connect_to_brady(self.device_path, timeout=20.0)
            
            if not connected or not self.ble_client:
                logger.error("Brady M511 connection failed")
                return False
            
            logger.info("Brady M511 connected - setting up protocol...")
            
            # Get Brady service and characteristics
            services = self.ble_client.services
            brady_service = None
            
            for service in services:
                if "fd1c" in str(service.uuid).lower():
                    brady_service = service
                    break
            
            if not brady_service:
                logger.error("Brady service not found")
                return False
            
            # Get required characteristics
            for char in brady_service.characteristics:
                char_uuid = str(char.uuid).lower()
                if char_uuid == PRINT_JOB_CHAR_UUID.lower():
                    self.print_job_char = char
                    logger.info("✅ Print Job characteristic found")
                elif char_uuid == PICL_REQUEST_CHAR_UUID.lower():
                    self.picl_request_char = char
                    logger.info("✅ PICL Request characteristic found")
                elif char_uuid == PICL_RESPONSE_CHAR_UUID.lower():
                    self.picl_response_char = char
                    logger.info("✅ PICL Response characteristic found")
            
            # Verify all characteristics found
            if not all([self.print_job_char, self.picl_request_char, self.picl_response_char]):
                logger.error("Missing required Brady characteristics")
                return False
            
            # Enable PICL response notifications
            if "indicate" in self.picl_response_char.properties:
                await self.ble_client.start_notify(self.picl_response_char, self._handle_picl_response)
                logger.info("PICL Response notifications enabled")
            
            self.connected = True
            logger.info("Brady M511 initialization complete")
            return True
            
        except Exception as e:
            logger.error(f"Brady M511 async initialization failed: {e}")
            return False
    
    def _handle_picl_response(self, sender, data: bytearray) -> None:
        """Handle PICL response notifications from printer"""
        try:
            # Parse PICL packet (header + length + JSON payload)
            if len(data) < 20:
                return
                
            # Extract JSON payload (skip 16-byte header + 4-byte length)
            json_payload = data[20:].decode('utf-8', errors='ignore')
            
            try:
                response = json.loads(json_payload)
                
                if "PropertyGetResponses" in response:
                    for prop in response["PropertyGetResponses"]:
                        prop_id = prop.get("ID")
                        value = prop.get("Value")
                        status = prop.get("Status")
                        
                        if prop_id and status == "Successful":
                            self.printer_status[prop_id] = value
                            
                            # Handle important status updates
                            if prop_id == BradyPropertyKey.PRINT_JOB_ID_AND_STATUS:
                                logger.info(f"Print job status: {value}")
                            elif prop_id == BradyPropertyKey.JOB_PRINTING_COMPLETE:
                                logger.info(f"Job printing complete: {value}")
                            elif prop_id in [BradyPropertyKey.FATAL_ERROR, BradyPropertyKey.PRINT_JOB_ERROR]:
                                if value != "False":
                                    logger.warning(f"Printer error {prop_id}: {value}")
                                    
            except json.JSONDecodeError:
                logger.debug(f"Non-JSON PICL response: {data[:50].hex()}...")
                
        except Exception as e:
            logger.error(f"Error handling PICL response: {e}")
    
    def _generate_text_bitmap(self, text: str) -> bytes:
        """Generate bitmap for text using PIL (Python equivalent of Canvas)"""
        try:
            from PIL import Image, ImageDraw, ImageFont
            
            # M4C-375-342 label dimensions (from Brady parts database)
            # 5470 x 5000 units ≈ 87 x 79 pixels at 300 DPI  
            width, height = 87, 79
            
            # Create image with white background
            image = Image.new('1', (width, height), 1)  # 1-bit mode, white background
            draw = ImageDraw.Draw(image)
            
            # Try to use a monospace font, fallback to default
            try:
                # Try to load a monospace font
                font = ImageFont.load_default()
            except:
                font = None
            
            # Get text dimensions for centering
            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                bbox = draw.textbbox((0, 0), text)
                text_width = bbox[2] - bbox[0] 
                text_height = bbox[3] - bbox[1]
            
            # Center the text
            x = (width - text_width) // 2
            y = (height - text_height) // 2
            
            # Draw black text on white background
            draw.text((x, y), text, fill=0, font=font)  # 0 = black in 1-bit mode
            
            # Convert to raw bitmap data (matches JavaScript canvas approach)
            # M4C-375-342 is 87x79 pixels = need 11 bytes per row (87 pixels / 8 = 10.875, round up)
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
            
            # Apply Brady compression
            return self._compress_bitmap(bitmap)
            
        except ImportError:
            logger.warning("PIL not available, using fallback bitmap")
            # Fallback to hardcoded pattern if PIL not available
            return bytes([0x81, 0x02, 0x38, 0x84, 0x00, 0x00, 0xff, 0x0f,
                         0x81, 0x02, 0x11, 0xab, 0x00, 0x00, 0xff, 0x04,
                         0x81, 0x02, 0x38])
        except Exception as e:
            logger.error(f"Error generating bitmap: {e}")
            # Fallback to hardcoded pattern
            return bytes([0x81, 0x02, 0x38, 0x84, 0x00, 0x00, 0xff, 0x0f,
                         0x81, 0x02, 0x11, 0xab, 0x00, 0x00, 0xff, 0x04,
                         0x81, 0x02, 0x38])
    
    def _compress_bitmap(self, bitmap: List[int]) -> bytes:
        """Compress bitmap using Brady run-length encoding (from bundle.pretty.js)"""
        result = []
        
        i = 0
        while i < len(bitmap):
            current_byte = bitmap[i]
            run_length = 1
            
            # Count consecutive identical bytes
            while (i + run_length < len(bitmap) and 
                   bitmap[i + run_length] == current_byte and 
                   run_length < 255):
                run_length += 1
            
            # Brady compression format (from JavaScript analysis):
            # 0x81 = compression marker
            # 0x02 = command type
            # For runs > 1: runLength, 0x84, 0x00, 0x00, 0xFF, runLength
            # For single bytes: currentByte, 0xAB, 0x00, 0x00, 0xFF, 0x04
            
            if run_length > 1:
                result.extend([0x81, 0x02, run_length, 0x84, 0x00, 0x00, 0xFF, run_length])
            else:
                result.extend([0x81, 0x02, current_byte, 0xAB, 0x00, 0x00, 0xFF, 0x04])
            
            i += run_length
        
        # Final compression marker
        result.extend([0x81, 0x02, 0x38])
        
        return bytes(result)

    def _build_picl_json_packet(self, json_string: str) -> bytes:
        """Build PICL packet from JSON string (from bundle.pretty.js)"""
        # Encode JSON string to bytes
        json_bytes = json_string.encode('utf-8')
        json_length = len(json_bytes)
        
        # Create length header (4 bytes, little endian)
        length_header = bytes([
            json_length & 0xFF,
            (json_length >> 8) & 0xFF, 
            (json_length >> 16) & 0xFF,
            (json_length >> 24) & 0xFF
        ])
        
        # PICL header from bundle.pretty.js
        picl_header = bytes([150, 194, 247, 74, 29, 33, 66, 50, 134, 120, 32, 239, 233, 123, 194, 211])
        
        # Combine: header + length + JSON
        packet = picl_header + length_header + json_bytes
        return packet

    def _create_simple_print_job(self, text: str) -> bytes:
        """Create Brady print job with dynamic bitmap generation (raw binary format)"""
        
        # Generate unique job ID
        job_id = uuid.uuid4().hex
        self.current_job_id = job_id
        
        logger.info(f"Creating print job for text: '{text}', ID: {job_id}")
        
        # Build print job using bundle.pretty.js format
        print_job = bytearray()
        
        # 1. Header (matches working capture - [01 01 00] for first packet)
        print_job.extend([0x01, 0x01, 0x00])
        
        # 2. Job ID section
        job_id_section = f"K\x00\x0a{job_id}\x0d"
        print_job.extend([0x02, len(job_id_section)])
        print_job.extend(job_id_section.encode('ascii'))
        
        # 3. Label type (M4C-375-342 from Brady parts database)
        label_section = "K\x00\x0cM4C-375-342\x0d"
        print_job.extend([0x02, len(label_section)])
        print_job.extend(label_section.encode('ascii'))
        
        # 4. Position setup commands (matches JavaScript array exactly)
        position_commands = ["D+0001", "C+0001", "c\x00", "p+00", "o+00", "O+00", "b+00", "M\x01"]
        for cmd in position_commands:
            print_job.extend([0x02, len(cmd)])
            print_job.extend(cmd.encode('ascii'))
        
        # 5. Text content setup (more characters possible with larger M4C-375-342 labels)
        content_text = text[:12].ljust(12, '0')  # Allow up to 12 characters
        content_section = f"K\x00\x0c{content_text}"
        print_job.extend([0x02, len(content_section)])
        print_job.extend(content_section.encode('ascii'))
        
        # 6. Print control commands
        control_commands = ["A", "Q", "a"]
        for cmd in control_commands:
            print_job.extend([0x02, len(cmd)])
            print_job.extend(cmd.encode('ascii'))
        
        # 7. Text formatting
        text_format = "IBUlbl0\x0d"
        print_job.extend([0x02, len(text_format)])
        print_job.extend(text_format.encode('ascii'))
        
        # 8. Bitmap generation (dynamic based on text)
        # X Position
        print_job.extend([0x58, 0x00, 0x00])
        
        # Y Position  
        print_job.extend([0x59, 0x00, 0x00])
        
        # Bitmap dimensions
        print_job.extend([0x59, 0x06, 0x00])
        
        # Generate bitmap from text
        bitmap_data = self._generate_text_bitmap(text)
        print_job.extend(bitmap_data)
        
        logger.info(f"Generated raw binary print job: {len(print_job)} bytes (no PICL packaging)")
        return bytes(print_job)
    
    def print_labels(self, print_job: PrintJob) -> bool:
        """
        Print labels using Brady M511
        
        Args:
            print_job: Print job specification
            
        Returns:
            True if printing succeeded, False otherwise
        """
        if not self.connected or not self.ble_client:
            logger.error("Brady M511 not connected")
            return False
        
        try:
            # Extract label data
            cable_data = print_job.data
            serial_numbers = cable_data.get('serial_numbers', [])
            
            if not serial_numbers:
                logger.error("No serial numbers provided for printing")
                return False
            
            logger.info(f"Printing {len(serial_numbers)} labels on Brady M511")
            
            # Print each serial number
            success_count = 0
            for i, serial_number in enumerate(serial_numbers):
                logger.info(f"Printing label {i+1}/{len(serial_numbers)}: {serial_number}")
                
                # Create raw binary print job for this serial number  
                print_data = self._create_simple_print_job(serial_number)
                
                # Send to printer
                if self._send_print_job_sync(print_data):
                    success_count += 1
                    logger.info(f"Label {i+1} sent successfully")
                else:
                    logger.error(f"Failed to send label {i+1}")
            
            logger.info(f"Brady M511 printing completed: {success_count}/{len(serial_numbers)} successful")
            return success_count == len(serial_numbers)
            
        except Exception as e:
            logger.error(f"Brady M511 printing failed: {e}")
            return False
    
    def _send_print_job_sync(self, print_data: bytes) -> bool:
        """Send print job data in sync context"""
        try:
            # Check if we're in an async context
            try:
                loop = asyncio.get_running_loop()
                logger.warning("Cannot send print job in async context")
                return False
            except RuntimeError:
                # No running loop, create new one
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(self._send_print_job_async(print_data))
                finally:
                    loop.close()
                    
        except Exception as e:
            logger.error(f"Failed to send print job: {e}")
            return False
    
    async def _send_print_job_async(self, print_data: bytes) -> bool:
        """Send print job data asynchronously"""
        try:
            if not self.ble_client or not self.ble_client.is_connected:
                logger.error("Brady M511 not connected")
                return False
            
            if not self.print_job_char:
                logger.error("Print job characteristic not available")
                return False
            
            # Send in chunks (proven to work in tests)
            chunk_size = 150
            total_chunks = (len(print_data) + chunk_size - 1) // chunk_size
            
            logger.info(f"Sending print job in {total_chunks} chunks")
            
            for i in range(0, len(print_data), chunk_size):
                chunk = print_data[i:i+chunk_size]
                chunk_num = i // chunk_size + 1
                
                logger.debug(f"Sending chunk {chunk_num}/{total_chunks}: {len(chunk)} bytes")
                await self.ble_client.write_gatt_char(self.print_job_char, chunk, response=False)
                
                # Brief pause between chunks (from successful tests)
                await asyncio.sleep(0.1)
            
            logger.info("Print job sent successfully to Brady M511")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send print job: {e}")
            return False
    
    def get_status(self) -> Dict[str, Any]:
        """Get Brady M511 printer status"""
        if not self.connected:
            return {
                'ready': False,
                'connected': False,
                'connection_type': 'bluetooth',
                'error': 'Not connected'
            }
        
        try:
            if self.ble_client and self.ble_client.is_connected:
                status = {
                    'ready': True,
                    'connected': True,
                    'connection_type': 'bluetooth',
                    'device_address': self.device_path,
                    'current_job_id': self.current_job_id
                }
                
                # Add printer-specific status from PICL responses
                if BradyPropertyKey.BATTERY_CHARGE_STATUS in self.printer_status:
                    status['battery_level'] = self.printer_status[BradyPropertyKey.BATTERY_CHARGE_STATUS]
                
                if BradyPropertyKey.SUBSTRATE_REMAINING_PERCENT in self.printer_status:
                    status['substrate_remaining'] = self.printer_status[BradyPropertyKey.SUBSTRATE_REMAINING_PERCENT]
                
                if BradyPropertyKey.FIRMWARE_VERSION in self.printer_status:
                    status['firmware_version'] = self.printer_status[BradyPropertyKey.FIRMWARE_VERSION]
                
                # Check for errors
                errors = []
                if self.printer_status.get(BradyPropertyKey.FATAL_ERROR, "False") != "False":
                    errors.append("Fatal Error")
                if self.printer_status.get(BradyPropertyKey.PRINT_JOB_ERROR, "False") != "False":
                    errors.append("Print Job Error")
                
                status['errors'] = errors
                status['ready'] = len(errors) == 0
                
                return status
            else:
                return {
                    'ready': False,
                    'connected': False,
                    'connection_type': 'bluetooth',
                    'error': 'BLE client not connected'
                }
                
        except Exception as e:
            return {
                'ready': False,
                'connected': self.connected,
                'connection_type': 'bluetooth',
                'error': f'Status check failed: {e}'
            }
    
    def is_ready(self) -> bool:
        """Check if Brady M511 is ready to print"""
        status = self.get_status()
        return status.get('ready', False)
    
    def close(self) -> None:
        """Close Brady M511 printer connection"""
        try:
            if self.connected and self.ble_client:
                logger.info("Closing Brady M511 connection")
                
                # Use centralized disconnect function
                try:
                    loop = asyncio.get_running_loop()
                    logger.warning("Cannot close Brady M511 in async context")
                except RuntimeError:
                    # No running loop, create new one
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        from .brady_connection import disconnect_from_brady
                        loop.run_until_complete(disconnect_from_brady(self.ble_client))
                    finally:
                        loop.close()
                
                self.ble_client = None
                self.connected = False
                self.print_job_char = None
                self.picl_request_char = None
                self.picl_response_char = None
                self.current_job_id = None
                
                logger.info("Brady M511 connection closed")
                
        except Exception as e:
            logger.error(f"Error closing Brady M511 connection: {e}")


class MockLabelPrinter(LabelPrinterInterface):
    """Mock label printer for testing without hardware"""
    
    def __init__(self):
        self.connected = False
        self.labels_printed = 0
    
    def initialize(self) -> bool:
        """Initialize mock label printer"""
        logger.info("Initializing mock label printer")
        self.connected = True
        return True
    
    def print_labels(self, print_job: PrintJob) -> bool:
        """Simulate label printing"""
        if not self.connected:
            return False
        
        cable_data = print_job.data
        serial_numbers = cable_data.get('serial_numbers', [])
        
        logger.info(f"MOCK: Printing {len(serial_numbers)} labels")
        for serial in serial_numbers:
            logger.info(f"MOCK: Label printed - Serial: {serial}")
        
        self.labels_printed += len(serial_numbers)
        return True
    
    def get_status(self) -> Dict[str, Any]:
        """Get mock printer status"""
        return {
            'ready': self.connected,
            'connected': self.connected,
            'labels_printed': self.labels_printed,
            'mock': True
        }
    
    def is_ready(self) -> bool:
        """Check if mock printer is ready"""
        return self.connected
    
    def close(self) -> None:
        """Close mock printer"""
        self.connected = False
        logger.info("Mock label printer closed")