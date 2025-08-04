"""
Raspberry Pi GPIO Interface Implementation

Handles GPIO operations for status LEDs, indicators, and control signals.
"""

import logging
from typing import Dict, Any
from .interfaces import GPIOInterface

logger = logging.getLogger(__name__)


class RaspberryPiGPIO(GPIOInterface):
    """Raspberry Pi GPIO implementation using RPi.GPIO library"""
    
    def __init__(self):
        self.initialized = False
        self.pin_assignments = {
            # Status LEDs
            'led_power': 18,
            'led_ready': 19,
            'led_testing': 20,
            'led_pass': 21,
            'led_fail': 22,
            'led_error': 23,
            
            # Control outputs
            'test_fixture_power': 24,
            'test_relay_1': 25,
            'test_relay_2': 26,
            
            # Input signals
            'emergency_stop': 2,
            'test_fixture_ready': 3,
            'door_interlock': 4,
        }
        self.gpio = None
    
    def initialize(self) -> bool:
        """Initialize Raspberry Pi GPIO"""
        try:
            # Import RPi.GPIO (only available on Raspberry Pi)
            try:
                import RPi.GPIO as GPIO
                self.gpio = GPIO
            except ImportError:
                logger.warning("RPi.GPIO not available - using mock GPIO")
                return self._initialize_mock()
            
            logger.info("Initializing Raspberry Pi GPIO")
            
            # Set GPIO mode
            self.gpio.setmode(self.gpio.BCM)
            self.gpio.setwarnings(False)
            
            # Setup output pins (LEDs and controls)
            output_pins = [
                'led_power', 'led_ready', 'led_testing', 
                'led_pass', 'led_fail', 'led_error',
                'test_fixture_power', 'test_relay_1', 'test_relay_2'
            ]
            
            for pin_name in output_pins:
                pin_number = self.pin_assignments[pin_name]
                self.gpio.setup(pin_number, self.gpio.OUT, initial=self.gpio.LOW)
                logger.debug(f"Setup GPIO pin {pin_number} ({pin_name}) as output")
            
            # Setup input pins with pull-up resistors
            input_pins = ['emergency_stop', 'test_fixture_ready', 'door_interlock']
            
            for pin_name in input_pins:
                pin_number = self.pin_assignments[pin_name]
                self.gpio.setup(pin_number, self.gpio.IN, pull_up_down=self.gpio.PUD_UP)
                logger.debug(f"Setup GPIO pin {pin_number} ({pin_name}) as input with pull-up")
            
            # Set initial state - power LED on
            self.set_status_led('led_power', True)
            
            self.initialized = True
            logger.info("Raspberry Pi GPIO initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize GPIO: {e}")
            return False
    
    def _initialize_mock(self) -> bool:
        """Initialize mock GPIO for development/testing"""
        logger.info("Initializing mock GPIO interface")
        self.initialized = True
        self.gpio = None  # Use None to indicate mock mode
        return True
    
    def set_status_led(self, led_name: str, state: bool) -> None:
        """Control status LED"""
        if not self.initialized:
            logger.error("GPIO not initialized")
            return
        
        if led_name not in self.pin_assignments:
            logger.error(f"Unknown LED: {led_name}")
            return
        
        pin_number = self.pin_assignments[led_name]
        
        if self.gpio:  # Real GPIO
            self.gpio.output(pin_number, self.gpio.HIGH if state else self.gpio.LOW)
            logger.debug(f"Set {led_name} (pin {pin_number}) to {'ON' if state else 'OFF'}")
        else:  # Mock GPIO
            logger.info(f"MOCK GPIO: {led_name} = {'ON' if state else 'OFF'}")
    
    def read_input(self, pin_name: str) -> bool:
        """Read digital input pin"""
        if not self.initialized:
            logger.error("GPIO not initialized")
            return False
        
        if pin_name not in self.pin_assignments:
            logger.error(f"Unknown input pin: {pin_name}")
            return False
        
        pin_number = self.pin_assignments[pin_name]
        
        if self.gpio:  # Real GPIO
            # Note: With pull-up resistors, LOW = pressed/closed, HIGH = open
            value = self.gpio.input(pin_number)
            return not value  # Invert for logical state
        else:  # Mock GPIO
            # For testing, simulate all inputs as "safe" state
            logger.debug(f"MOCK GPIO: Reading {pin_name} = False")
            return False
    
    def set_output(self, pin_name: str, state: bool) -> None:
        """Set digital output pin"""
        if not self.initialized:
            logger.error("GPIO not initialized")
            return
        
        if pin_name not in self.pin_assignments:
            logger.error(f"Unknown output pin: {pin_name}")
            return
        
        pin_number = self.pin_assignments[pin_name]
        
        if self.gpio:  # Real GPIO
            self.gpio.output(pin_number, self.gpio.HIGH if state else self.gpio.LOW)
            logger.debug(f"Set {pin_name} (pin {pin_number}) to {'HIGH' if state else 'LOW'}")
        else:  # Mock GPIO
            logger.info(f"MOCK GPIO: {pin_name} = {'HIGH' if state else 'LOW'}")
    
    def get_pin_states(self) -> Dict[str, bool]:
        """Get current state of all pins (for debugging)"""
        states = {}
        
        if not self.initialized:
            return states
        
        for pin_name, pin_number in self.pin_assignments.items():
            if self.gpio:
                # This would require keeping track of output states
                # as GPIO doesn't always allow reading output pin states
                states[pin_name] = False  # Placeholder
            else:
                states[pin_name] = False  # Mock state
        
        return states
    
    def cleanup(self) -> None:
        """Clean up GPIO resources"""
        try:
            if self.initialized:
                logger.info("Cleaning up GPIO resources")
                
                if self.gpio:
                    # Turn off all LEDs except power
                    for led in ['led_ready', 'led_testing', 'led_pass', 'led_fail', 'led_error']:
                        self.set_status_led(led, False)
                    
                    # Turn off all control outputs
                    for output in ['test_fixture_power', 'test_relay_1', 'test_relay_2']:
                        self.set_output(output, False)
                    
                    # Clean up GPIO library
                    self.gpio.cleanup()
                
                self.initialized = False
                self.gpio = None
                
        except Exception as e:
            logger.error(f"Error during GPIO cleanup: {e}")


class MockGPIO(GPIOInterface):
    """Mock GPIO for testing without Raspberry Pi hardware"""
    
    def __init__(self):
        self.initialized = False
        self.led_states = {}
        self.output_states = {}
        self.input_states = {}
    
    def initialize(self) -> bool:
        """Initialize mock GPIO"""
        logger.info("Initializing mock GPIO interface")
        self.initialized = True
        return True
    
    def set_status_led(self, led_name: str, state: bool) -> None:
        """Mock LED control"""
        self.led_states[led_name] = state
        logger.info(f"MOCK LED: {led_name} = {'ON' if state else 'OFF'}")
    
    def read_input(self, pin_name: str) -> bool:
        """Mock input reading"""
        # Return safe default states
        return self.input_states.get(pin_name, False)
    
    def set_output(self, pin_name: str, state: bool) -> None:
        """Mock output control"""
        self.output_states[pin_name] = state
        logger.info(f"MOCK OUTPUT: {pin_name} = {'HIGH' if state else 'LOW'}")
    
    def cleanup(self) -> None:
        """Mock cleanup"""
        logger.info("Mock GPIO cleanup")
        self.initialized = False
        self.led_states.clear()
        self.output_states.clear()
        self.input_states.clear()