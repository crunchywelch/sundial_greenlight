import signal
import sys
import logging

from greenlight.ui import UIBase
from greenlight.screen_manager import ScreenManager
from greenlight.screens import SplashScreen
from greenlight.config import APP_NAME, EXIT_MESSAGE
from greenlight.hardware.interfaces import hardware_manager
from greenlight.hardware.scanner import ZebraDS2208Scanner, MockBarcodeScanner
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
        # Create hardware instances without initialization (lazy loading)
        print(f"🚀 Starting {APP_NAME}...")
        
        # Create hardware instances - initialization happens when first used
        scanner = ZebraDS2208Scanner()
        card_printer = MockCardPrinter()
        gpio = MockGPIO()
        
        # Set up hardware manager with lazy initialization
        hardware_manager.set_hardware(
            scanner=scanner,
            label_printer=None,  # No label printer configured
            card_printer=card_printer,
            gpio=gpio
        )
        
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

