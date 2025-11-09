import signal
import sys
import logging

from greenlight.ui import UIBase
from greenlight.screen_manager import ScreenManager
from greenlight.screens import SplashScreen
from greenlight.config import APP_NAME, EXIT_MESSAGE

def signal_handler(sig, frame):
    """Handle Ctrl-C gracefully"""
    print(f"\n\n🛑 Exiting {APP_NAME}...")
    print(EXIT_MESSAGE)
    sys.exit(0)

def main():
    # Set up graceful exit on Ctrl-C
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Start application
        print(f"🚀 Starting {APP_NAME}...")

        ui = UIBase()
        screen_manager = ScreenManager(ui)
        screen_manager.push_screen(SplashScreen)
        screen_manager.run()
        
    except KeyboardInterrupt:
        # Fallback handler in case signal handler doesn't catch it
        print(f"\n\n🛑 Exiting {APP_NAME}...")
        print(EXIT_MESSAGE)
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        print(f"Exiting {APP_NAME}...")
        sys.exit(1)

if __name__ == "__main__":
    main()

