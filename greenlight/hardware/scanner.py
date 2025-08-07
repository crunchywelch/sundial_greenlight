"""
Barcode Scanner Implementation

Handles barcode scanning for cable serial numbers during testing.
Specifically optimized for Zebra DS2208 USB HID scanner.
"""

import logging
import time
import threading
import select
import sys
from typing import Optional, Callable
from .interfaces import ScannerInterface, ScanResult

logger = logging.getLogger(__name__)


class ZebraDS2208Scanner(ScannerInterface):
    """Zebra DS2208 USB HID barcode scanner implementation"""
    
    def __init__(self):
        """
        Initialize Zebra DS2208 scanner
        
        Zebra DS2208 specifications:
        - USB HID interface (appears as keyboard)
        - Vendor ID: 0x05e0 (Symbol Technologies/Zebra)
        - Product ID: 0x1900 (DS2208)
        - 2D imager with 832x640 resolution
        - Optimized for small label scanning
        """
        self.vendor_id = 0x05e0  # Zebra/Symbol Technologies
        self.product_id = 0x1900  # DS2208
        self.device_path = None
        self.connected = False
        self.scanning = False
        self._scan_buffer = ""
        self._scan_callback: Optional[Callable[[ScanResult], None]] = None
        self._scan_thread: Optional[threading.Thread] = None
    
    def initialize(self) -> bool:
        """Initialize Zebra DS2208 scanner"""
        try:
            logger.info("Initializing Zebra DS2208 barcode scanner")
            
            # Check if scanner is connected via USB
            if self._detect_zebra_scanner():
                self.connected = True
                logger.info("Zebra DS2208 scanner detected and ready")
                return True
            else:
                logger.warning("Zebra DS2208 scanner not detected - using simulation mode")
                self.connected = True  # Allow simulation mode for development
                return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Zebra DS2208 scanner: {e}")
            return False
    
    def _detect_zebra_scanner(self) -> bool:
        """Detect if Zebra DS2208 is connected via USB"""
        try:
            # Check lsusb output for Zebra scanner with timeout
            import subprocess
            result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5.0)
            
            # Look for Zebra/Symbol device
            usb_devices = result.stdout.lower()
            zebra_detected = ('05e0:' in usb_devices or 
                             'symbol' in usb_devices or 
                             'zebra' in usb_devices)
            
            if zebra_detected:
                logger.info("Zebra DS2208 detected in USB devices")
                # Try to find the input device path
                self._find_input_device()
                return True
            else:
                logger.warning("Zebra DS2208 not found in USB devices")
                return False
                
        except Exception as e:
            logger.error(f"Error detecting Zebra scanner: {e}")
            return False
    
    def _find_input_device(self):
        """Find the input device path for the scanner"""
        try:
            import glob
            import subprocess
            
            # Look for input devices that might be the scanner
            input_devices = glob.glob('/dev/input/event*')
            
            for device in input_devices:
                try:
                    # Check device info with timeout
                    result = subprocess.run(['udevadm', 'info', '--query=property', device], 
                                          capture_output=True, text=True, timeout=3.0)
                    device_info = result.stdout.lower()
                    
                    # Look for Zebra/Symbol in device properties
                    if ('symbol' in device_info or 'zebra' in device_info or 
                        '05e0' in device_info):
                        self.device_path = device
                        logger.info(f"Found Zebra scanner at {device}")
                        break
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.error(f"Error finding input device: {e}")
    
    def scan(self, timeout: float = 5.0) -> Optional[ScanResult]:
        """
        Scan for barcode with timeout using Zebra DS2208
        
        Args:
            timeout: Maximum time to wait for scan in seconds
            
        Returns:
            ScanResult if successful, None if timeout or error
        """
        if not self.connected:
            logger.error("Zebra scanner not connected")
            return None
        
        try:
            logger.info(f"Starting Zebra DS2208 barcode scan (timeout: {timeout}s)")
            
            if self.device_path:
                # Try to read from actual device
                return self._scan_from_device(timeout)
            else:
                # Fallback to keyboard input capture
                return self._scan_from_keyboard(timeout)
            
        except Exception as e:
            logger.error(f"Error during Zebra scan: {e}")
            return None
    
    def _scan_from_device(self, timeout: float) -> Optional[ScanResult]:
        """Scan using direct device input"""
        try:
            import struct
            
            # Open the input device
            with open(self.device_path, 'rb') as device:
                logger.info("Listening for Zebra DS2208 input...")
                
                scan_data = ""
                start_time = time.time()
                
                # Input event structure: time(8), type(2), code(2), value(4)
                event_size = struct.calcsize('llHHI')
                
                while time.time() - start_time < timeout:
                    # Use select to check for input with timeout
                    ready, _, _ = select.select([device], [], [], 0.1)
                    
                    if ready:
                        data = device.read(event_size)
                        if len(data) == event_size:
                            _, _, event_type, key_code, value = struct.unpack('llHHI', data)
                            
                            # EV_KEY events (type 1) with press (value 1)
                            if event_type == 1 and value == 1:
                                char = self._keycode_to_char(key_code)
                                if char == '\n':  # Enter key signals end of scan
                                    if scan_data:
                                        return ScanResult(
                                            data=scan_data.strip(),
                                            format="CODE128",  # Zebra DS2208 default
                                            timestamp=time.time(),
                                            success=True
                                        )
                                elif char and char.isprintable():
                                    scan_data += char
                
                logger.warning("Zebra scan timeout")
                return None
                
        except Exception as e:
            logger.error(f"Error reading from Zebra device: {e}")
            return self._scan_from_keyboard(timeout)
    
    def _scan_from_keyboard(self, timeout: float) -> Optional[ScanResult]:
        """Fallback: capture scanner input as keyboard events"""
        try:
            logger.info("Using keyboard capture for Zebra scanner")
            
            # Since Zebra DS2208 appears as keyboard, we can capture its input
            # This is a simplified approach - in production you might want
            # to use libraries like evdev or pynput for better input handling
            
            old_settings = None
            try:
                import termios
                import tty
                
                # Save terminal settings
                old_settings = termios.tcgetattr(sys.stdin)
                tty.setraw(sys.stdin.fileno())
                
                scan_data = ""
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        char = sys.stdin.read(1)
                        
                        if ord(char) == 13 or ord(char) == 10:  # Enter key
                            if scan_data:
                                return ScanResult(
                                    data=scan_data.strip(),
                                    format="CODE128",
                                    timestamp=time.time(),
                                    success=True
                                )
                        elif char.isprintable():
                            scan_data += char
                
                return None
                
            finally:
                if old_settings:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                    
        except Exception as e:
            logger.error(f"Error in keyboard capture: {e}")
            return None
    
    def _keycode_to_char(self, keycode: int) -> Optional[str]:
        """Convert Linux keycode to character for Zebra scanner"""
        # Basic keycode mapping for common characters
        keymap = {
            2: '1', 3: '2', 4: '3', 5: '4', 6: '5', 7: '6', 8: '7', 9: '8', 10: '9', 11: '0',
            16: 'q', 17: 'w', 18: 'e', 19: 'r', 20: 't', 21: 'y', 22: 'u', 23: 'i', 24: 'o', 25: 'p',
            30: 'a', 31: 's', 32: 'd', 33: 'f', 34: 'g', 35: 'h', 36: 'j', 37: 'k', 38: 'l',
            44: 'z', 45: 'x', 46: 'c', 47: 'v', 48: 'b', 49: 'n', 50: 'm',
            28: '\n',  # Enter
            57: ' ',   # Space
        }
        
        char = keymap.get(keycode)
        return char.upper() if char and char.isalpha() else char
    
    def start_continuous_scan(self, callback: Callable[[ScanResult], None]) -> bool:
        """
        Start continuous scanning mode
        
        Args:
            callback: Function to call when barcode is scanned
            
        Returns:
            True if started successfully
        """
        if not self.connected:
            logger.error("Scanner not connected")
            return False
        
        if self.scanning:
            logger.warning("Scanner already in continuous mode")
            return True
        
        try:
            self._scan_callback = callback
            self.scanning = True
            
            # Start background scanning thread
            self._scan_thread = threading.Thread(target=self._continuous_scan_worker, daemon=True)
            self._scan_thread.start()
            
            logger.info("Started continuous barcode scanning")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start continuous scanning: {e}")
            return False
    
    def stop_continuous_scan(self) -> None:
        """Stop continuous scanning mode"""
        if self.scanning:
            self.scanning = False
            self._scan_callback = None
            
            if self._scan_thread:
                self._scan_thread.join(timeout=1.0)
                self._scan_thread = None
            
            logger.info("Stopped continuous barcode scanning")
    
    def _continuous_scan_worker(self) -> None:
        """Background worker for continuous scanning"""
        while self.scanning:
            try:
                # TODO: Implement actual continuous scanning logic
                time.sleep(0.1)  # Prevent busy waiting
                
            except Exception as e:
                logger.error(f"Error in continuous scan worker: {e}")
                break
    
    def is_connected(self) -> bool:
        """Check if scanner is connected"""
        return self.connected
    
    def close(self) -> None:
        """Close scanner connection"""
        try:
            self.stop_continuous_scan()
            
            if self.connected:
                logger.info("Closing barcode scanner connection")
                # TODO: Close actual scanner connection
                self.connected = False
                self.device = None
                
        except Exception as e:
            logger.error(f"Error closing scanner: {e}")


class MockBarcodeScanner(ScannerInterface):
    """Mock barcode scanner for testing without hardware"""
    
    def __init__(self):
        self.connected = False
        self.scan_count = 0
    
    def initialize(self) -> bool:
        """Initialize mock scanner"""
        logger.info("Initializing mock barcode scanner")
        self.connected = True
        return True
    
    def scan(self, timeout: float = 5.0) -> Optional[ScanResult]:
        """Simulate barcode scan"""
        if not self.connected:
            return None
        
        # Simulate scan delay
        time.sleep(0.5)
        
        # Generate mock scan result
        self.scan_count += 1
        mock_serial = f"SD{self.scan_count:06d}"
        
        result = ScanResult(
            data=mock_serial,
            format="CODE128",
            timestamp=time.time(),
            success=True
        )
        
        logger.info(f"MOCK: Scanned barcode - {mock_serial}")
        return result
    
    def is_connected(self) -> bool:
        """Check if mock scanner is connected"""
        return self.connected
    
    def close(self) -> None:
        """Close mock scanner"""
        self.connected = False
        logger.info("Mock barcode scanner closed")