import random
import time
import json
import logging
from dataclasses import dataclass
from typing import Optional, Tuple

# Optional serial import for Arduino support
try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    serial = None

logger = logging.getLogger(__name__)


@dataclass
class TestResult:
    """Results from cable testing"""
    continuity_pass: bool
    resistance_adc: int  # Raw ADC value (0-1023), pass threshold indicates < 0.5Ω
    capacitance_pf: float
    test_time: float
    cable_sku: str
    operator: str
    arduino_unit_id: int


class MockArduinoTester:
    """Mock Arduino testing interface that simulates serial communication"""
    
    def __init__(self, arduino_unit_id=None):
        # Simulate different Arduino testing units
        self.arduino_unit_id = arduino_unit_id or random.randint(1, 3)  # Mock units 1, 2, or 3
        
        # Acceptable ranges for different cable types
        self.resistance_ranges = {
            "TS-TS": (0.1, 0.5),     # Normal instrument cables
            "RA-TS": (0.1, 0.5),     # Right angle variants
            "TRS-TRS": (0.05, 0.3),  # Balanced cables (lower resistance)
            "XLR": (0.05, 0.2),     # XLR cables (even lower)
        }
        
        self.capacitance_ranges = {
            "3": (80, 120),   # 3ft cables
            "6": (150, 200),  # 6ft cables  
            "10": (250, 350), # 10ft cables
            "15": (380, 480), # 15ft cables
            "20": (500, 650), # 20ft cables
        }
    
    def get_expected_ranges(self, cable_type) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Get expected resistance and capacitance ranges for cable type"""
        connector_type = cable_type.connector_type
        length = cable_type.length
        
        resistance_range = self.resistance_ranges.get(connector_type, (0.1, 0.5))
        capacitance_range = self.capacitance_ranges.get(length, (100, 300))
        
        return resistance_range, capacitance_range
    
    def mock_continuity_test(self) -> bool:
        """Mock continuity test - occasionally fails to simulate real conditions"""
        # 95% pass rate for good cables
        return random.random() > 0.05
    
    def mock_resistance_test(self, cable_type) -> float:
        """Mock resistance measurement within expected range"""
        resistance_range, _ = self.get_expected_ranges(cable_type)
        min_r, max_r = resistance_range
        
        # 90% chance of being in range, 10% chance of being out of range
        if random.random() < 0.9:
            # Good measurement within range
            return round(random.uniform(min_r, max_r), 3)
        else:
            # Bad measurement outside range
            if random.random() < 0.5:
                return round(random.uniform(max_r * 1.2, max_r * 2.0), 3)  # Too high
            else:
                return round(random.uniform(0.001, min_r * 0.8), 3)  # Too low
    
    def mock_capacitance_test(self, cable_type) -> float:
        """Mock capacitance measurement within expected range"""
        _, capacitance_range = self.get_expected_ranges(cable_type)
        min_c, max_c = capacitance_range
        
        # 90% chance of being in range, 10% chance of being out of range
        if random.random() < 0.9:
            # Good measurement within range
            return round(random.uniform(min_c, max_c), 1)
        else:
            # Bad measurement outside range
            if random.random() < 0.5:
                return round(random.uniform(max_c * 1.2, max_c * 1.8), 1)  # Too high
            else:
                return round(random.uniform(min_c * 0.3, min_c * 0.8), 1)  # Too low
    
    def run_full_test(self, cable_type, operator: str) -> TestResult:
        """Run complete test sequence with realistic timing and GPIO feedback"""
        from greenlight.hardware.interfaces import hardware_manager
        
        start_time = time.time()
        
        # Set testing LED on
        if hardware_manager.gpio:
            hardware_manager.gpio.set_status_led('led_testing', True)
            hardware_manager.gpio.set_status_led('led_ready', False)
        
        # Simulate test sequence timing
        continuity = self.mock_continuity_test()
        time.sleep(0.5)  # Continuity test delay
        
        resistance = self.mock_resistance_test(cable_type)
        time.sleep(1.0)  # Resistance test delay
        
        capacitance = self.mock_capacitance_test(cable_type)
        time.sleep(1.0)  # Capacitance test delay
        
        test_time = time.time() - start_time
        
        # Mock ADC value - good cables have ADC > 700
        resistance_adc = random.randint(750, 850) if resistance < 0.5 else random.randint(400, 650)

        result = TestResult(
            continuity_pass=continuity,
            resistance_adc=resistance_adc,
            capacitance_pf=capacitance,
            test_time=test_time,
            cable_sku=cable_type.sku,
            operator=operator,
            arduino_unit_id=self.arduino_unit_id
        )
        
        # Update LEDs based on test results
        if hardware_manager.gpio:
            hardware_manager.gpio.set_status_led('led_testing', False)
            
            # Validate results to determine pass/fail
            validation = self.validate_results(result, cable_type)
            if validation['overall_pass']:
                hardware_manager.gpio.set_status_led('led_pass', True)
                hardware_manager.gpio.set_status_led('led_fail', False)
            else:
                hardware_manager.gpio.set_status_led('led_pass', False)
                hardware_manager.gpio.set_status_led('led_fail', True)
        
        return result
    
    def validate_results(self, result: TestResult, cable_type) -> dict:
        """Validate test results against expected ranges"""
        _, capacitance_range = self.get_expected_ranges(cable_type)

        # ADC > 700 indicates good low resistance (< 0.5Ω)
        resistance_pass = result.resistance_adc >= 700
        capacitance_pass = capacitance_range[0] <= result.capacitance_pf <= capacitance_range[1]

        overall_pass = result.continuity_pass and resistance_pass and capacitance_pass

        return {
            "overall_pass": overall_pass,
            "continuity_pass": result.continuity_pass,
            "resistance_pass": resistance_pass,
            "capacitance_pass": capacitance_pass,
            "resistance_adc": result.resistance_adc,
            "capacitance_range": capacitance_range
        }


class ArduinoATmega32Tester:
    """Real Arduino Mega 2560 testing interface via USB serial communication"""
    
    def __init__(self, port: Optional[str] = None, baudrate: int = 9600, arduino_unit_id: Optional[int] = None):
        """
        Initialize Arduino tester
        
        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0'). If None, will auto-detect
            baudrate: Serial communication speed (9600 is Arduino default)
            arduino_unit_id: Override unit ID, otherwise will query from Arduino
        """
        if not SERIAL_AVAILABLE:
            raise ImportError("pyserial library not installed. Install with: pip install pyserial")
        
        self.port = port
        self.baudrate = baudrate
        self.arduino_unit_id = arduino_unit_id
        self.serial_connection = None
        self.connected = False
        
        # Command/response protocol
        self.commands = {
            'test_cable': 'TEST_CABLE',
            'get_unit_id': 'GET_UNIT_ID',
            'get_status': 'GET_STATUS',
            'calibrate': 'CALIBRATE'
        }
    
    def initialize(self) -> bool:
        """Initialize serial connection to Arduino"""
        try:
            if not self.port:
                self.port = self._find_arduino_port()
                if not self.port:
                    logger.error("No Arduino found on any serial port")
                    return False
            
            logger.info(f"Connecting to Arduino on {self.port} at {self.baudrate} baud")
            
            self.serial_connection = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=5.0,  # 5 second timeout for responses
                write_timeout=2.0
            )
            
            # Wait for Arduino to initialize (bootloader delay)
            time.sleep(2.0)
            
            # Test connection and get unit ID
            if self._test_connection():
                self.connected = True
                logger.info(f"Arduino Mega 2560 tester connected successfully (Unit #{self.arduino_unit_id})")
                return True
            else:
                logger.error("Arduino connection test failed")
                self._disconnect()
                return False
                
        except Exception as e:
            logger.error(f"Failed to initialize Arduino: {e}")
            self._disconnect()
            return False
    
    def _find_arduino_port(self) -> Optional[str]:
        """Auto-detect Arduino on serial ports"""
        logger.info("Scanning for Arduino on serial ports...")
        
        ports = serial.tools.list_ports.comports()
        
        for port in ports:
            # Look for common Arduino identifiers
            if any(identifier in port.description.lower() for identifier in 
                   ['arduino', 'ch340', 'ch341', 'ftdi', 'atmega']):
                logger.info(f"Found potential Arduino at {port.device}: {port.description}")
                return port.device
            
            # Also check common Linux Arduino ports
            if port.device.startswith(('/dev/ttyUSB', '/dev/ttyACM')):
                logger.info(f"Found serial device at {port.device}: {port.description}")
                return port.device
        
        logger.warning("No Arduino-like devices found")
        return None
    
    def _test_connection(self) -> bool:
        """Test Arduino connection and get unit ID"""
        try:
            # Clear any pending data
            self.serial_connection.reset_input_buffer()
            self.serial_connection.reset_output_buffer()
            
            # Request unit ID
            response = self._send_command(self.commands['get_unit_id'])
            if response and response.startswith('UNIT_ID:'):
                unit_id_str = response.split(':')[1]
                if not self.arduino_unit_id:
                    self.arduino_unit_id = int(unit_id_str)
                logger.info(f"Arduino responded with Unit ID: {self.arduino_unit_id}")
                return True
            else:
                logger.error(f"Invalid response from Arduino: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Arduino connection test failed: {e}")
            return False
    
    def _send_command(self, command: str, timeout: float = 5.0) -> Optional[str]:
        """Send command to Arduino and wait for response"""
        try:
            if not self.connected or not self.serial_connection:
                logger.error("Arduino not connected")
                return None
            
            # Send command
            command_bytes = (command + '\n').encode('utf-8')
            self.serial_connection.write(command_bytes)
            logger.debug(f"Sent to Arduino: {command}")
            
            # Read response
            start_time = time.time()
            response = ""
            
            while time.time() - start_time < timeout:
                if self.serial_connection.in_waiting > 0:
                    char = self.serial_connection.read(1).decode('utf-8')
                    if char == '\n':
                        response = response.strip()
                        logger.debug(f"Received from Arduino: {response}")
                        return response
                    else:
                        response += char
                time.sleep(0.01)  # Small delay to prevent busy waiting
            
            logger.warning(f"Arduino command timeout: {command}")
            return None
            
        except Exception as e:
            logger.error(f"Error sending command to Arduino: {e}")
            return None
    
    def run_full_test(self, cable_type, operator: str) -> TestResult:
        """Run complete cable test via Arduino"""
        from greenlight.hardware.interfaces import hardware_manager
        
        if not self.connected:
            logger.error("Arduino not connected - cannot run test")
            raise RuntimeError("Arduino tester not connected")
        
        start_time = time.time()
        
        # Set testing LED on
        if hardware_manager.gpio:
            hardware_manager.gpio.set_status_led('led_testing', True)
            hardware_manager.gpio.set_status_led('led_ready', False)
        
        try:
            # Send test command to Arduino
            logger.info(f"Starting Arduino cable test for {cable_type.sku}")
            response = self._send_command(self.commands['test_cable'], timeout=30.0)
            
            if not response:
                raise RuntimeError("No response from Arduino during test")
            
            # Parse Arduino response
            # Expected format: "TEST_RESULT:CONTINUITY:1:RESISTANCE:0.25:CAPACITANCE:145.2"
            result = self._parse_test_response(response, cable_type, operator, start_time)
            
            # Update LEDs based on test results
            if hardware_manager.gpio:
                hardware_manager.gpio.set_status_led('led_testing', False)
                
                # Validate results to determine pass/fail
                validation = self.validate_results(result, cable_type)
                if validation['overall_pass']:
                    hardware_manager.gpio.set_status_led('led_pass', True)
                    hardware_manager.gpio.set_status_led('led_fail', False)
                else:
                    hardware_manager.gpio.set_status_led('led_pass', False)
                    hardware_manager.gpio.set_status_led('led_fail', True)
            
            return result
            
        except Exception as e:
            # Set error LED
            if hardware_manager.gpio:
                hardware_manager.gpio.set_status_led('led_testing', False)
                hardware_manager.gpio.set_status_led('led_error', True)
            
            logger.error(f"Arduino test failed: {e}")
            raise
    
    def _parse_test_response(self, response: str, cable_type, operator: str, start_time: float) -> TestResult:
        """Parse Arduino test response into TestResult"""
        try:
            # Parse response format: "TEST_RESULT:CONTINUITY:1:RESISTANCE_ADC:789:CAPACITANCE:145.2"
            if not response.startswith('TEST_RESULT:'):
                raise ValueError(f"Invalid response format: {response}")

            parts = response.split(':')

            # Extract values
            continuity_pass = bool(int(parts[2]))
            resistance_adc = int(parts[4])  # Raw ADC value
            capacitance_pf = float(parts[6])

            test_time = time.time() - start_time

            return TestResult(
                continuity_pass=continuity_pass,
                resistance_adc=resistance_adc,
                capacitance_pf=capacitance_pf,
                test_time=test_time,
                cable_sku=cable_type.sku,
                operator=operator,
                arduino_unit_id=self.arduino_unit_id
            )
            
        except Exception as e:
            logger.error(f"Failed to parse Arduino response: {response}, error: {e}")
            raise ValueError(f"Invalid Arduino response: {response}")
    
    def get_expected_ranges(self, cable_type) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """Get expected resistance and capacitance ranges for cable type"""
        # Same ranges as mock version for consistency
        resistance_ranges = {
            "TS-TS": (0.1, 0.5),     # Normal instrument cables
            "RA-TS": (0.1, 0.5),     # Right angle variants
            "TRS-TRS": (0.05, 0.3),  # Balanced cables (lower resistance)
            "XLR": (0.05, 0.2),     # XLR cables (even lower)
        }
        
        capacitance_ranges = {
            "3": (80, 120),   # 3ft cables
            "6": (150, 200),  # 6ft cables  
            "10": (250, 350), # 10ft cables
            "15": (380, 480), # 15ft cables
            "20": (500, 650), # 20ft cables
        }
        
        connector_type = cable_type.connector_type
        length = cable_type.length
        
        resistance_range = resistance_ranges.get(connector_type, (0.1, 0.5))
        capacitance_range = capacitance_ranges.get(length, (100, 300))
        
        return resistance_range, capacitance_range
    
    def validate_results(self, result: TestResult, cable_type) -> dict:
        """Validate test results against expected ranges"""
        _, capacitance_range = self.get_expected_ranges(cable_type)

        # ADC > 700 indicates good low resistance (< 0.5Ω)
        resistance_pass = result.resistance_adc >= 700
        capacitance_pass = capacitance_range[0] <= result.capacitance_pf <= capacitance_range[1]

        overall_pass = result.continuity_pass and resistance_pass and capacitance_pass

        return {
            "overall_pass": overall_pass,
            "continuity_pass": result.continuity_pass,
            "resistance_pass": resistance_pass,
            "capacitance_pass": capacitance_pass,
            "resistance_adc": result.resistance_adc,
            "capacitance_range": capacitance_range
        }
    
    def get_status(self) -> dict:
        """Get Arduino status"""
        if not self.connected:
            return {"connected": False, "error": "Not connected"}
        
        try:
            response = self._send_command(self.commands['get_status'])
            if response and response.startswith('STATUS:'):
                # Parse status response
                return {"connected": True, "status": response}
            else:
                return {"connected": True, "status": "Unknown"}
        except Exception as e:
            return {"connected": False, "error": str(e)}
    
    def calibrate(self) -> bool:
        """Run Arduino calibration sequence"""
        if not self.connected:
            logger.error("Arduino not connected - cannot calibrate")
            return False
        
        try:
            logger.info("Starting Arduino calibration...")
            response = self._send_command(self.commands['calibrate'], timeout=60.0)
            
            if response and 'CALIBRATION_COMPLETE' in response:
                logger.info("Arduino calibration completed successfully")
                return True
            else:
                logger.error(f"Arduino calibration failed: {response}")
                return False
                
        except Exception as e:
            logger.error(f"Arduino calibration error: {e}")
            return False
    
    def _disconnect(self):
        """Close serial connection"""
        try:
            if self.serial_connection:
                self.serial_connection.close()
                self.serial_connection = None
            self.connected = False
        except Exception as e:
            logger.error(f"Error disconnecting Arduino: {e}")
    
    def close(self):
        """Close Arduino connection"""
        logger.info("Closing Arduino connection")
        self._disconnect()