import signal
import sys
import time
import logging

from greenlight.ui import UIBase
from greenlight.screen_manager import ScreenManager
from greenlight.screens import SplashScreen
from greenlight.config import (
    APP_NAME, EXIT_MESSAGE,
    USE_REAL_PRINTERS, TSC_PRINTER_IP, TSC_PRINTER_PORT, TSC_LABEL_WIDTH_MM, TSC_LABEL_HEIGHT_MM,
    USE_REAL_ARDUINO, ARDUINO_PORT, ARDUINO_BAUDRATE
)

def signal_handler(sig, frame):
    """Handle Ctrl-C gracefully"""
    print(f"\n\n🛑 Exiting {APP_NAME}...")
    print(EXIT_MESSAGE)
    sys.exit(0)

def init_hardware():
    """Initialize hardware devices (printers, scanners, cable tester, etc.)

    This is non-blocking - app will start even if hardware is unavailable
    """
    label_printer = None
    cable_tester = None
    scanner = None

    try:
        from greenlight.hardware.interfaces import hardware_manager

        # Initialize TSC label printer
        if USE_REAL_PRINTERS:
            print("🖨️  Initializing TSC label printer...")
            from greenlight.hardware.tsc_label_printer import TSCLabelPrinter

            label_printer = TSCLabelPrinter(
                ip_address=TSC_PRINTER_IP,
                port=TSC_PRINTER_PORT,
                label_width_mm=TSC_LABEL_WIDTH_MM,
                label_height_mm=TSC_LABEL_HEIGHT_MM
            )

            # Try to initialize
            if label_printer.initialize():
                print(f"✅ TSC printer ready at {TSC_PRINTER_IP}")
            else:
                print(f"⚠️  TSC printer not responding at {TSC_PRINTER_IP}")
                print("   Label printing will be unavailable")
        else:
            print("🖨️  Using mock label printer (USE_REAL_PRINTERS=false)")
            from greenlight.hardware.tsc_label_printer import MockTSCLabelPrinter

            label_printer = MockTSCLabelPrinter(ip_address=TSC_PRINTER_IP, port=TSC_PRINTER_PORT)
            label_printer.initialize()
            print("✅ Mock label printer initialized")

        # Initialize Arduino cable tester
        if USE_REAL_ARDUINO:
            print("🔌 Initializing Arduino cable tester...")
            from greenlight.hardware.cable_tester import ArduinoCableTester

            cable_tester = ArduinoCableTester(
                port=ARDUINO_PORT,  # None for auto-detect
                baudrate=ARDUINO_BAUDRATE
            )

            # Try to initialize
            if cable_tester.initialize():
                print(f"✅ Cable tester ready: {cable_tester.tester_id} on {cable_tester.port}")
            else:
                print("⚠️  Cable tester not found")
                print("   Cable testing will be unavailable")
        else:
            print("🔌 Using mock cable tester (USE_REAL_ARDUINO=false)")
            from greenlight.hardware.cable_tester import MockCableTester

            cable_tester = MockCableTester()
            cable_tester.initialize()
            print("✅ Mock cable tester initialized")

        # Initialize MQTT barcode scanner
        # Scanner daemon must be running to publish scans to MQTT
        print("📷 Initializing MQTT barcode scanner...")
        from greenlight.hardware.mqtt_scanner import MQTTScanner

        scanner = MQTTScanner()
        if scanner.initialize():
            print("✅ MQTT scanner connected (subscribing to scanner/barcode)")
            # Disable Shopify webhooks while Greenlight is running
            scanner.set_webhooks_enabled(False)
            print("🔇 Shopify webhooks paused (Greenlight active)")
        else:
            print("⚠️  MQTT scanner not connected")
            print("   Check that mosquitto and scanner daemon are running")

        # Set all hardware in manager
        hardware_manager.set_hardware(
            label_printer=label_printer,
            cable_tester=cable_tester,
            scanner=scanner
        )

    except Exception as e:
        # Don't crash the app, just warn
        print(f"⚠️  Hardware initialization issue: {e}")
        print("   Some hardware features may not work")
        print("   Continuing startup...")


def check_shopify_connection():
    """Validate and refresh Shopify connection on startup

    This is non-blocking - app will start even if Shopify is unavailable
    """
    try:
        from greenlight import shopify_client
        import os

        # Only check if Shopify is configured
        if not os.getenv("SHOPIFY_SHOP_URL"):
            return  # Shopify not configured, skip check

        print("🔗 Checking Shopify connection...")

        # Try to get a session (this will auto-refresh token if needed)
        session = shopify_client.get_shopify_session()
        shopify_client.close_shopify_session()

        print("✅ Shopify connection OK")

    except Exception as e:
        # Don't crash the app, just warn
        print(f"⚠️  Shopify connection issue: {e}")
        print("   Customer assignment features may not work")
        print("   Continuing startup...")


def shutdown_hardware():
    """Re-enable Shopify webhooks and shut down all hardware"""
    try:
        from greenlight.hardware.interfaces import hardware_manager
        scanner = hardware_manager.scanner
        if scanner and hasattr(scanner, 'set_webhooks_enabled'):
            scanner.set_webhooks_enabled(True)
            print("🔔 Shopify webhooks restored")
            time.sleep(0.1)  # ensure message is sent before disconnect
        hardware_manager.shutdown()
    except Exception as e:
        print(f"⚠️  Hardware shutdown issue: {e}")


def main():
    # Set up graceful exit on Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)

    try:
        # Start application
        print(f"🚀 Starting {APP_NAME}...")

        # Initialize hardware (non-blocking)
        init_hardware()

        # Check Shopify connection (non-blocking)
        check_shopify_connection()

        ui = UIBase()
        screen_manager = ScreenManager(ui)
        screen_manager.push_screen(SplashScreen)
        screen_manager.run()

    except (KeyboardInterrupt, SystemExit):
        print(f"\n\n🛑 Exiting {APP_NAME}...")
        print(EXIT_MESSAGE)
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        print(f"Exiting {APP_NAME}...")
    finally:
        shutdown_hardware()

if __name__ == "__main__":
    main()

