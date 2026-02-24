"""
MQTT-based barcode scanner client.

Subscribes to MQTT topic where the scanner daemon publishes barcodes.
Provides the same interface as BarcodeScanner for drop-in replacement.
"""

import json
import queue
import threading
import time
import logging
from typing import Optional
from greenlight.hardware.interfaces import ScanResult

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.warning("paho-mqtt not installed. Install with: pip install paho-mqtt")

# MQTT Configuration (must match scanner_daemon.py)
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "scanner/barcode"
MQTT_CONTROL_TOPIC = "scanner/webhook_control"


class MQTTScanner:
    """
    MQTT-based scanner client that subscribes to barcode scan events.

    Provides the same interface as BarcodeScanner for compatibility.
    """

    def __init__(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self.broker = broker
        self.port = port
        self.mqtt_client = None
        self.scan_queue = queue.Queue()
        self.connected = False
        self.running = False
        self._paused = False
        self._webhook_state_payload = None
        self._connect_lock = threading.Lock()

        # For compatibility with BarcodeScanner interface
        self.device_name = "MQTT Scanner Client"
        self.device_path = f"mqtt://{broker}:{port}/{MQTT_TOPIC}"

    def initialize(self) -> bool:
        """Initialize MQTT connection"""
        if not MQTT_AVAILABLE:
            logger.error("MQTT library not available")
            return False

        with self._connect_lock:
            if self.mqtt_client and self.connected:
                return True

            try:
                # Create client with unique ID
                client_id = f"greenlight-scanner-{int(time.time() * 1000) % 10000}"
                self.mqtt_client = mqtt.Client(
                    callback_api_version=CallbackAPIVersion.VERSION2,
                    client_id=client_id
                )

                # Set callbacks
                self.mqtt_client.on_connect = self._on_connect
                self.mqtt_client.on_disconnect = self._on_disconnect
                self.mqtt_client.on_message = self._on_message

                # Set Last Will: if Greenlight crashes, re-enable webhooks
                self.mqtt_client.will_set(MQTT_CONTROL_TOPIC, payload="webhooks_on", qos=1, retain=True)

                # Connect
                self.mqtt_client.connect(self.broker, self.port, keepalive=60)
                self.mqtt_client.loop_start()

                # Wait briefly for connection
                for _ in range(20):  # Wait up to 2 seconds
                    if self.connected:
                        return True
                    time.sleep(0.1)

                logger.warning("MQTT connection timeout")
                return False

            except Exception as e:
                logger.error(f"Failed to connect to MQTT broker: {e}")
                return False

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker"""
        if reason_code == 0:
            logger.info(f"Connected to MQTT broker at {self.broker}:{self.port}")
            self.connected = True
            # Subscribe to scanner topic
            client.subscribe(MQTT_TOPIC, qos=1)
            logger.info(f"Subscribed to topic: {MQTT_TOPIC}")
            # Re-assert webhook state on reconnect
            if self._webhook_state_payload:
                self.mqtt_client.publish(MQTT_CONTROL_TOPIC, self._webhook_state_payload, qos=1, retain=True)
        else:
            logger.error(f"MQTT connection failed: {reason_code}")
            self.connected = False

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Callback when disconnected from MQTT broker"""
        self.connected = False
        if reason_code != 0:
            logger.warning(f"Unexpected MQTT disconnect: {reason_code}")

    def _on_message(self, client, userdata, msg):
        """Callback when a message is received"""
        if self._paused:
            return
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
            barcode = payload.get('barcode')
            if barcode:
                logger.debug(f"Received scan: {barcode}")
                self.scan_queue.put(barcode)
        except json.JSONDecodeError:
            # Handle plain text messages
            barcode = msg.payload.decode('utf-8').strip()
            if barcode:
                self.scan_queue.put(barcode)
        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def is_connected(self) -> bool:
        """Check if connected to MQTT broker"""
        return self.connected

    def start_scanning(self):
        """Start receiving scans (connect to MQTT if needed)"""
        if not self.connected:
            self.initialize()
        self.running = True

    def stop_scanning(self):
        """Stop receiving scans"""
        self.running = False

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

    def scan(self, timeout: float = 5.0) -> Optional[ScanResult]:
        """Scan for barcode with timeout - returns ScanResult for ScannerInterface compatibility"""
        barcode = self.get_scan(timeout=timeout)
        if barcode:
            return ScanResult(
                data=barcode,
                format="CODE128",  # Assume CODE128 for cable barcodes
                timestamp=time.time(),
                success=True
            )
        return None

    def close(self) -> None:
        """Close connection - alias for shutdown() for ScannerInterface compatibility"""
        self.shutdown()

    def clear_queue(self):
        """Clear any pending scans from the queue"""
        while not self.scan_queue.empty():
            try:
                self.scan_queue.get_nowait()
            except queue.Empty:
                break

    def publish(self, topic, payload, qos=1, retain=False):
        """Publish a message to an MQTT topic"""
        if self.mqtt_client and self.connected:
            result = self.mqtt_client.publish(topic, payload, qos=qos, retain=retain)
            return result.rc == mqtt.MQTT_ERR_SUCCESS
        return False

    def set_webhooks_enabled(self, enabled):
        """Control Shopify webhooks in the scanner daemon via MQTT"""
        payload = "webhooks_on" if enabled else "webhooks_off"
        self._webhook_state_payload = payload
        return self.publish(MQTT_CONTROL_TOPIC, payload, qos=1, retain=True)

    def pause(self):
        """Pause scan processing (ignore incoming barcode messages)"""
        self._paused = True
        self.clear_queue()

    def resume(self):
        """Resume scan processing"""
        self._paused = False
        self.clear_queue()

    def shutdown(self):
        """Clean shutdown"""
        self.running = False
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass
            self.mqtt_client = None
        self.connected = False


# Global MQTT scanner instance
_mqtt_scanner_instance = None


def get_mqtt_scanner() -> MQTTScanner:
    """Get the global MQTT scanner instance"""
    global _mqtt_scanner_instance
    if _mqtt_scanner_instance is None:
        _mqtt_scanner_instance = MQTTScanner()
    return _mqtt_scanner_instance
