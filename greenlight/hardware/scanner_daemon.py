#!/usr/bin/env python3
"""
Scanner daemon - owns the USB barcode scanner and publishes scans to MQTT.

This daemon runs as a systemd service and makes scans available to any
subscriber (Greenlight TUI, Shopify app, etc.) via MQTT.

Usage:
    python -m greenlight.hardware.scanner_daemon

MQTT Topic:
    scanner/barcode - Published when a barcode is scanned

Message format (JSON):
    {"barcode": "SD000123", "timestamp": 1234567890.123}
"""

import json
import signal
import sys
import time
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('scanner_daemon')

try:
    import paho.mqtt.client as mqtt
    from paho.mqtt.enums import CallbackAPIVersion
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False
    logger.error("paho-mqtt not installed. Install with: pip install paho-mqtt")

from greenlight.hardware.barcode_scanner import get_evdev_scanner, EVDEV_AVAILABLE

# MQTT Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "scanner/barcode"
MQTT_CLIENT_ID = "scanner-daemon"

# Reconnect settings
RECONNECT_DELAY = 5  # seconds


class ScannerDaemon:
    """Daemon that reads from USB scanner and publishes to MQTT"""

    def __init__(self):
        self.scanner = None
        self.mqtt_client = None
        self.running = False

    def setup_mqtt(self) -> bool:
        """Initialize MQTT client"""
        if not MQTT_AVAILABLE:
            logger.error("MQTT library not available")
            return False

        try:
            self.mqtt_client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=MQTT_CLIENT_ID
            )
            self.mqtt_client.on_connect = self._on_mqtt_connect
            self.mqtt_client.on_disconnect = self._on_mqtt_disconnect

            logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self.mqtt_client.loop_start()
            return True

        except Exception as e:
            logger.error(f"Failed to connect to MQTT: {e}")
            return False

    def _on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        """Callback when connected to MQTT broker"""
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Callback when disconnected from MQTT broker"""
        if reason_code != 0:
            logger.warning(f"Unexpected MQTT disconnect: {reason_code}")

    def setup_scanner(self) -> bool:
        """Initialize the barcode scanner"""
        if not EVDEV_AVAILABLE:
            logger.error("evdev library not available")
            return False

        self.scanner = get_evdev_scanner()

        if not self.scanner.initialize():
            logger.error("Failed to initialize scanner - device not found")
            return False

        logger.info(f"Scanner initialized: {self.scanner.device_name}")
        logger.info(f"Device path: {self.scanner.device_path}")
        return True

    def publish_scan(self, barcode: str):
        """Publish a scanned barcode to MQTT"""
        if not self.mqtt_client:
            return

        message = json.dumps({
            "barcode": barcode,
            "timestamp": time.time()
        })

        try:
            result = self.mqtt_client.publish(MQTT_TOPIC, message, qos=1)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.info(f"Published: {barcode}")
            else:
                logger.warning(f"Failed to publish: {barcode} (rc={result.rc})")
        except Exception as e:
            logger.error(f"Error publishing to MQTT: {e}")

    def run(self):
        """Main daemon loop"""
        logger.info("Starting scanner daemon...")

        # Setup MQTT
        if not self.setup_mqtt():
            logger.error("MQTT setup failed, exiting")
            return 1

        # Setup scanner (retry loop)
        while not self.setup_scanner():
            logger.warning(f"Scanner not found, retrying in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)
            if not self.running:
                return 0

        # Start scanning
        self.scanner.start_scanning()
        self.running = True

        logger.info(f"Scanner daemon running. Publishing to MQTT topic: {MQTT_TOPIC}")
        logger.info("Press Ctrl+C to stop")

        try:
            while self.running:
                # Check for scanned barcodes
                barcode = self.scanner.get_scan(timeout=0.5)
                if barcode:
                    self.publish_scan(barcode)

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            self.shutdown()

        return 0

    def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down scanner daemon...")
        self.running = False

        if self.scanner:
            self.scanner.shutdown()

        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        logger.info("Scanner daemon stopped")

    def handle_signal(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self.running = False


def main():
    """Entry point"""
    if not MQTT_AVAILABLE:
        print("Error: paho-mqtt not installed. Install with: pip install paho-mqtt")
        return 1

    if not EVDEV_AVAILABLE:
        print("Error: evdev not installed. Install with: pip install evdev")
        return 1

    daemon = ScannerDaemon()

    # Setup signal handlers
    signal.signal(signal.SIGTERM, daemon.handle_signal)
    signal.signal(signal.SIGINT, daemon.handle_signal)

    return daemon.run()


if __name__ == "__main__":
    sys.exit(main())
