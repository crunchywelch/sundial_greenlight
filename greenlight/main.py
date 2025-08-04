import signal
import sys
import logging

from greenlight.ui import UIBase
from greenlight.screen_manager import ScreenManager
from greenlight.screens import SplashScreen
from greenlight.config import APP_NAME, EXIT_MESSAGE
from greenlight.hardware.interfaces import hardware_manager
from greenlight.hardware.scanner import ZebraDS2208Scanner, MockBarcodeScanner
from greenlight.hardware.label_printer import MockLabelPrinter
from greenlight.hardware.card_printer import MockCardPrinter
from greenlight.hardware.gpio import MockGPIO

def signal_handler(sig, frame):
    """Handle Ctrl-C gracefully"""
    print(f"\n\n🛑 Exiting {APP_NAME}...")
    hardware_manager.shutdown()
    print(EXIT_MESSAGE)
    sys.exit(0)

def main():
    # Set up graceful exit on Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Initialize hardware manager with real/mock devices
        print(f"🔧 Initializing {APP_NAME} hardware...")
        
        # Try to use real Zebra DS2208 scanner, fallback to mock
        try:
            scanner = ZebraDS2208Scanner()
            print("📱 Attempting Zebra DS2208 scanner initialization...")
        except Exception as e:
            print(f"⚠️  Zebra scanner unavailable, using mock: {e}")
            scanner = MockBarcodeScanner()
        
        label_printer = MockLabelPrinter()
        card_printer = MockCardPrinter()
        gpio = MockGPIO()
        
        hardware_success = hardware_manager.initialize(
            scanner=scanner,
            label_printer=label_printer,
            card_printer=card_printer,
            gpio=gpio
        )
        
        if hardware_success:
            print("✅ Hardware initialized successfully")
        else:
            print("⚠️  Some hardware failed to initialize - continuing with available devices")
        
        ui = UIBase()
        screen_manager = ScreenManager(ui)
        screen_manager.push_screen(SplashScreen)
        screen_manager.run()
        
    except KeyboardInterrupt:
        # Fallback handler in case signal handler doesn't catch it
        print(f"\n\n🛑 Exiting {APP_NAME}...")
        hardware_manager.shutdown()
        print(EXIT_MESSAGE)
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        hardware_manager.shutdown()
        print(f"Exiting {APP_NAME}...")
        sys.exit(1)

if __name__ == "__main__":
    main()

