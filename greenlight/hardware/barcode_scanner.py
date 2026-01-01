"""
Barcode scanner interface using evdev for direct HID input device access.
Based on scantest.py - works well over SSH without GUI focus.
"""

try:
    from evdev import InputDevice, categorize, ecodes, list_devices
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    print("Warning: evdev not installed. Install with: pip install evdev")

import os
import sys
import time
import re
from typing import Optional, Tuple
import threading
import queue

# Zebra DS2208 Scanner VID:PID
ZEBRA_DS2208_VID_PID = (0x05e0, 0x1200)

# Accept only these characters in the final code
ACCEPT_PATTERN = re.compile(r'[A-Za-z0-9._\-\/]+')

# Flush the buffer if there's a brief idle after last key
IDLE_FLUSH_SEC = 0.08

# Keymap for barcode characters (only define if evdev is available)
if EVDEV_AVAILABLE:
    KEYMAP = {
        ecodes.KEY_0: '0', ecodes.KEY_1: '1', ecodes.KEY_2: '2', ecodes.KEY_3: '3',
        ecodes.KEY_4: '4', ecodes.KEY_5: '5', ecodes.KEY_6: '6', ecodes.KEY_7: '7',
        ecodes.KEY_8: '8', ecodes.KEY_9: '9',
        ecodes.KEY_A: 'a', ecodes.KEY_B: 'b', ecodes.KEY_C: 'c', ecodes.KEY_D: 'd', ecodes.KEY_E: 'e',
        ecodes.KEY_F: 'f', ecodes.KEY_G: 'g', ecodes.KEY_H: 'h', ecodes.KEY_I: 'i', ecodes.KEY_J: 'j',
        ecodes.KEY_K: 'k', ecodes.KEY_L: 'l', ecodes.KEY_M: 'm', ecodes.KEY_N: 'n', ecodes.KEY_O: 'o',
        ecodes.KEY_P: 'p', ecodes.KEY_Q: 'q', ecodes.KEY_R: 'r', ecodes.KEY_S: 's', ecodes.KEY_T: 't',
        ecodes.KEY_U: 'u', ecodes.KEY_V: 'v', ecodes.KEY_W: 'w', ecodes.KEY_X: 'x', ecodes.KEY_Y: 'y',
        ecodes.KEY_Z: 'z',
        ecodes.KEY_MINUS: '-', ecodes.KEY_DOT: '.', ecodes.KEY_SLASH: '/',
        ecodes.KEY_KP0: '0', ecodes.KEY_KP1: '1', ecodes.KEY_KP2: '2', ecodes.KEY_KP3: '3', ecodes.KEY_KP4: '4',
        ecodes.KEY_KP5: '5', ecodes.KEY_KP6: '6', ecodes.KEY_KP7: '7', ecodes.KEY_KP8: '8', ecodes.KEY_KP9: '9',
    }
else:
    KEYMAP = {}


class BarcodeScanner:
    """Barcode scanner using evdev for direct device access"""

    def __init__(self):
        self.device = None
        self.device_path = None
        self.device_name = None
        self.scan_queue = queue.Queue()
        self.scan_thread = None
        self.running = False

    def list_input_devices(self):
        """List all available input devices"""
        devices = []
        for path in list_devices():
            dev = InputDevice(path)
            vid = getattr(getattr(dev, "info", None), "vendor", 0)
            pid = getattr(getattr(dev, "info", None), "product", 0)
            devices.append((path, dev.name or "?", vid, pid))
        return sorted(devices, key=lambda t: t[0])

    def find_scanner_device(self) -> Optional[Tuple[str, str, int, int]]:
        """Find the scanner device automatically"""
        devices = self.list_input_devices()
        if not devices:
            return None

        # Prefer exact Zebra DS2208 VID:PID
        for path, name, vid, pid in devices:
            if (vid, pid) == ZEBRA_DS2208_VID_PID:
                return (path, name, vid, pid)

        # Otherwise look for devices with "scanner" in the name
        for path, name, vid, pid in devices:
            if "scanner" in name.lower():
                return (path, name, vid, pid)

        return None

    def initialize(self) -> bool:
        """Initialize the scanner device"""
        if not EVDEV_AVAILABLE:
            return False

        try:
            device_info = self.find_scanner_device()
            if not device_info:
                return False

            path, name, vid, pid = device_info

            # Try to use stable by-id symlink if available
            byid = None
            try:
                for entry in os.listdir("/dev/input/by-id"):
                    p = os.path.join("/dev/input/by-id", entry)
                    if os.path.islink(p) and os.path.realpath(p).endswith(os.path.basename(path)):
                        byid = p
                        break
            except Exception:
                pass

            self.device_path = byid or path
            self.device = InputDevice(self.device_path)
            self.device_name = name

            return True

        except Exception as e:
            print(f"Scanner initialization error: {e}")
            return False

    def is_connected(self) -> bool:
        """Check if scanner is connected and ready"""
        return self.device is not None

    def start_scanning(self):
        """Start the background scanning thread"""
        if self.running:
            return

        if not self.is_connected():
            if not self.initialize():
                return

        self.running = True
        self.scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.scan_thread.start()

    def stop_scanning(self):
        """Stop the background scanning thread"""
        self.running = False
        if self.scan_thread:
            self.scan_thread.join(timeout=2.0)
            self.scan_thread = None

    def _scan_loop(self):
        """Background thread that continuously reads from scanner"""
        if not self.device:
            return

        buf = []
        last_key_time = time.monotonic()

        try:
            while self.running:
                try:
                    # Read events from device (non-blocking)
                    for ev in self.device.read():
                        last_key_time = time.monotonic()

                        if ev.type != ecodes.EV_KEY:
                            continue

                        key = categorize(ev)
                        if key.keystate != key.key_down:
                            continue

                        kc = key.keycode

                        # Check for Enter (end of scan)
                        if (kc == 'KEY_ENTER' or kc == 'KEY_KPENTER' or
                            (isinstance(kc, list) and ('KEY_ENTER' in kc or 'KEY_KPENTER' in kc))):
                            self._emit_barcode(buf)
                            buf.clear()
                            continue

                        # Add character to buffer
                        ch = KEYMAP.get(key.scancode)
                        if ch:
                            buf.append(ch)

                    # Idle flush (for scanners that don't send Enter)
                    if buf and (time.monotonic() - last_key_time) >= IDLE_FLUSH_SEC:
                        self._emit_barcode(buf)
                        buf.clear()

                    time.sleep(0.01)

                except BlockingIOError:
                    # No data available - check for idle flush
                    if buf and (time.monotonic() - last_key_time) >= IDLE_FLUSH_SEC:
                        self._emit_barcode(buf)
                        buf.clear()
                    time.sleep(0.01)

        except Exception as e:
            print(f"Scanner thread error: {e}")

    def _emit_barcode(self, buf):
        """Process and emit a complete barcode"""
        raw = ''.join(buf).strip()
        if not raw:
            return

        # Extract valid barcode pattern
        m = ACCEPT_PATTERN.search(raw)
        if m:
            barcode = m.group(0)
            self.scan_queue.put(barcode)

    def get_scan(self, timeout: float = 0.1) -> Optional[str]:
        """Get a scanned barcode from the queue (non-blocking with timeout)"""
        try:
            return self.scan_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def wait_for_scan(self, timeout: float = 30.0) -> Optional[str]:
        """Wait for a barcode scan with timeout"""
        try:
            return self.scan_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def clear_queue(self):
        """Clear any pending scans from the queue"""
        while not self.scan_queue.empty():
            try:
                self.scan_queue.get_nowait()
            except queue.Empty:
                break

    def shutdown(self):
        """Clean shutdown of scanner"""
        self.stop_scanning()
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None


# Global scanner instance
_scanner_instance = None

# Use MQTT scanner by default (requires scanner daemon running)
# Set to False to use direct evdev access (legacy mode)
USE_MQTT_SCANNER = True


def get_scanner():
    """
    Get the global scanner instance.

    By default, returns an MQTTScanner that subscribes to the scanner daemon.
    Set USE_MQTT_SCANNER = False for direct evdev access (legacy mode).
    """
    global _scanner_instance
    if _scanner_instance is None:
        if USE_MQTT_SCANNER:
            from greenlight.hardware.mqtt_scanner import MQTTScanner
            _scanner_instance = MQTTScanner()
        else:
            _scanner_instance = BarcodeScanner()
    return _scanner_instance


def get_evdev_scanner() -> BarcodeScanner:
    """Get a direct evdev scanner (for use by scanner daemon)"""
    return BarcodeScanner()
