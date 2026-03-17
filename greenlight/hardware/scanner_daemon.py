#!/usr/bin/env python3
"""
Scanner daemon - owns the USB barcode scanner and publishes scans to MQTT.

This daemon runs as a systemd service and makes scans available to any
subscriber (Greenlight TUI, Shopify app, etc.) via MQTT.

It also POSTs scans to the Shopify app's SSE endpoint for real-time
browser updates.

Usage:
    python -m greenlight.hardware.scanner_daemon

MQTT Topic:
    scanner/barcode - Published when a barcode is scanned

HTTP Webhooks:
    POST https://greenlight.sundialwire.com/api/scanner-events
    POST https://greenlightdev.sundialwire.com/api/scanner-events

Message format (JSON):
    {"barcode": "SD000123", "timestamp": 1234567890.123}
"""

import json
import signal
import sys
import time
import logging
import threading

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

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logger.warning("requests not installed - HTTP webhook disabled")

from greenlight.hardware.barcode_scanner import get_evdev_scanner, EVDEV_AVAILABLE

# MQTT Configuration
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "scanner/barcode"
MQTT_CONTROL_TOPIC = "scanner/webhook_control"
MQTT_CLIENT_ID = "scanner-daemon"

# HTTP Webhook Configuration (Shopify app SSE endpoints)
WEBHOOK_URLS = [
    "https://greenlight.sundialwire.com/api/scanner-events",
    "https://greenlightdev.sundialwire.com/api/scanner-events",
]
WEBHOOK_TIMEOUT = 2  # seconds
WEBHOOK_ENABLED = True  # Set to False to disable HTTP posting

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
            self.mqtt_client.on_message = self._on_mqtt_message

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
            client.subscribe(MQTT_CONTROL_TOPIC, qos=1)
            logger.info(f"Subscribed to control topic: {MQTT_CONTROL_TOPIC}")
        else:
            logger.error(f"MQTT connection failed: {reason_code}")

    def _on_mqtt_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        """Callback when disconnected from MQTT broker"""
        if reason_code != 0:
            logger.warning(f"Unexpected MQTT disconnect: {reason_code}")

    def _on_mqtt_message(self, client, userdata, msg):
        """Handle incoming MQTT messages (webhook control)"""
        global WEBHOOK_ENABLED
        if msg.topic == MQTT_CONTROL_TOPIC:
            payload = msg.payload.decode('utf-8').strip()
            if payload == 'webhooks_off':
                WEBHOOK_ENABLED = False
                logger.info("Webhooks DISABLED via MQTT control")
            elif payload == 'webhooks_on':
                WEBHOOK_ENABLED = True
                logger.info("Webhooks ENABLED via MQTT control")

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
        """Publish a scanned barcode to MQTT and HTTP webhook"""
        timestamp = time.time()

        # Publish to MQTT
        if self.mqtt_client:
            message = json.dumps({
                "barcode": barcode,
                "timestamp": timestamp
            })

            try:
                result = self.mqtt_client.publish(MQTT_TOPIC, message, qos=1)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    logger.info(f"MQTT published: {barcode}")
                else:
                    logger.warning(f"MQTT failed: {barcode} (rc={result.rc})")
            except Exception as e:
                logger.error(f"MQTT error: {e}")

        # POST to HTTP webhooks (fire and forget in background threads)
        if WEBHOOK_ENABLED and REQUESTS_AVAILABLE:
            for url in WEBHOOK_URLS:
                threading.Thread(
                    target=self._post_to_webhook,
                    args=(barcode, url),
                    daemon=True
                ).start()

    def _post_to_webhook(self, barcode: str, url: str):
        """POST scan to HTTP webhook (runs in background thread)"""
        try:
            response = requests.post(
                url,
                json={"serial": barcode},
                timeout=WEBHOOK_TIMEOUT
            )
            if response.ok:
                logger.debug(f"Webhook posted to {url}: {barcode}")
            else:
                logger.warning(f"Webhook failed {url}: {response.status_code}")
        except requests.exceptions.Timeout:
            logger.warning(f"Webhook timeout: {url}")
        except requests.exceptions.ConnectionError:
            logger.debug(f"Webhook connection failed (server may be down): {url}")
        except Exception as e:
            logger.warning(f"Webhook error {url}: {e}")

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
