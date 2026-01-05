"""
Arduino Cable Tester Serial Interface

Communicates with Arduino Mega 2560 cable tester via USB serial.
Supports continuity testing, resistance testing, and calibration.

Communication: USB serial at 9600 baud
Protocol: Text-based command/response (CONT, RES, CAL, STATUS, ID, RESET)
"""

import serial
import serial.tools.list_ports
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


@dataclass
class ContinuityResult:
    """Result from continuity test"""
    passed: bool
    tip_to_tip: bool
    tip_to_sleeve: bool
    sleeve_to_sleeve: bool
    sleeve_to_tip: bool
    reason: Optional[str] = None  # REVERSED, CROSSED, NO_CABLE, TIP_OPEN, SLEEVE_OPEN


@dataclass
class ResistanceResult:
    """Result from resistance test"""
    passed: bool
    adc_value: int
    calibrated: bool
    calibration_adc: Optional[int] = None
    milliohms: Optional[int] = None
    ohms: Optional[float] = None


@dataclass
class CalibrationResult:
    """Result from calibration"""
    success: bool
    adc_value: Optional[int] = None
    error: Optional[str] = None


class CableTesterInterface(ABC):
    """Abstract interface for cable testers"""

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the cable tester"""
        pass

    @abstractmethod
    def run_continuity_test(self) -> ContinuityResult:
        """Run continuity/polarity test"""
        pass

    @abstractmethod
    def run_resistance_test(self) -> ResistanceResult:
        """Run resistance test"""
        pass

    @abstractmethod
    def calibrate(self) -> CalibrationResult:
        """Calibrate with zero-ohm reference"""
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """Get tester status"""
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if tester is ready"""
        pass

    @abstractmethod
    def close(self) -> None:
        """Close connection"""
        pass


class ArduinoCableTester(CableTesterInterface):
    """Arduino Mega 2560 cable tester implementation"""

    def __init__(self, port: Optional[str] = None, baudrate: int = 9600, timeout: float = 5.0):
        """
        Initialize Arduino cable tester

        Args:
            port: Serial port path (e.g., /dev/ttyACM0). Auto-detected if None.
            baudrate: Serial baudrate (default 9600)
            timeout: Read timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial: Optional[serial.Serial] = None
        self.connected = False
        self.tester_id: Optional[str] = None

    def _find_arduino_port(self) -> Optional[str]:
        """Auto-detect Arduino serial port"""
        ports = serial.tools.list_ports.comports()
        for port in ports:
            # Arduino Mega 2560 typically shows as ttyACM* on Linux
            if 'ttyACM' in port.device or 'Arduino' in (port.description or ''):
                logger.info(f"Found Arduino at {port.device}: {port.description}")
                return port.device
            # Also check for ttyUSB* (FTDI-based)
            if 'ttyUSB' in port.device:
                logger.info(f"Found potential Arduino at {port.device}: {port.description}")
                return port.device
        return None

    def initialize(self) -> bool:
        """Initialize connection to Arduino cable tester"""
        try:
            # Auto-detect port if not specified
            if self.port is None:
                self.port = self._find_arduino_port()
                if self.port is None:
                    logger.error("No Arduino cable tester found")
                    return False

            # Open serial connection
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )

            # Wait for Arduino to reset after serial connection
            time.sleep(2.0)

            # Clear any startup messages
            self.serial.reset_input_buffer()

            # Verify connection by getting ID
            self._send_command("ID")
            response = self._read_response()

            if response and response.startswith("ID:"):
                self.tester_id = response.split(":")[1]
                self.connected = True
                logger.info(f"Arduino cable tester initialized: {self.tester_id} on {self.port}")
                return True
            else:
                logger.error(f"Unexpected response from cable tester: {response}")
                self.close()
                return False

        except serial.SerialException as e:
            logger.error(f"Failed to connect to cable tester: {e}")
            self.connected = False
            return False

    def _send_command(self, command: str) -> None:
        """Send command to Arduino"""
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial connection not open")

        self.serial.write(f"{command}\n".encode('utf-8'))
        self.serial.flush()
        logger.debug(f"Sent: {command}")

    def _read_response(self, timeout: Optional[float] = None) -> Optional[str]:
        """Read response line from Arduino"""
        if not self.serial:
            return None

        old_timeout = self.serial.timeout
        if timeout is not None:
            self.serial.timeout = timeout

        try:
            line = self.serial.readline().decode('utf-8').strip()
            logger.debug(f"Received: {line}")
            return line if line else None
        except serial.SerialException as e:
            logger.error(f"Serial read error: {e}")
            return None
        finally:
            self.serial.timeout = old_timeout

    def _read_until_response(self, prefix: str, timeout: float = 5.0) -> Optional[str]:
        """Read lines until we get one starting with the expected prefix"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = self._read_response(timeout=0.5)
            if response:
                if response.startswith(prefix):
                    return response
                elif response.startswith("ERROR:"):
                    logger.error(f"Tester error: {response}")
                    return response
                else:
                    # Log other messages (debug output, etc.)
                    logger.debug(f"Skipping: {response}")
        return None

    def run_continuity_test(self) -> ContinuityResult:
        """
        Run continuity/polarity test

        Returns:
            ContinuityResult with test outcome

        Response format: RESULT:PASS/FAIL:TT:x:TS:x:SS:x:ST:x[:REASON:xxx]
        """
        if not self.connected:
            raise RuntimeError("Cable tester not connected")

        self._send_command("CONT")
        response = self._read_until_response("RESULT:", timeout=10.0)

        if not response:
            raise RuntimeError("No response from continuity test")

        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")

        # Parse response: RESULT:PASS:TT:1:TS:0:SS:1:ST:0
        parts = response.split(":")

        passed = parts[1] == "PASS"

        # Parse raw readings
        tt = int(parts[3]) == 1  # tip_to_tip
        ts = int(parts[5]) == 1  # tip_to_sleeve
        ss = int(parts[7]) == 1  # sleeve_to_sleeve
        st = int(parts[9]) == 1  # sleeve_to_tip

        # Parse failure reason if present
        reason = None
        if "REASON" in response:
            reason_idx = parts.index("REASON")
            reason = parts[reason_idx + 1]

        return ContinuityResult(
            passed=passed,
            tip_to_tip=tt,
            tip_to_sleeve=ts,
            sleeve_to_sleeve=ss,
            sleeve_to_tip=st,
            reason=reason
        )

    def run_resistance_test(self) -> ResistanceResult:
        """
        Run resistance test

        Returns:
            ResistanceResult with test outcome

        Response format: RES:PASS/FAIL:ADC:xxx[:CAL:xxx:MOHM:xxx:OHM:xxx]
        """
        if not self.connected:
            raise RuntimeError("Cable tester not connected")

        self._send_command("RES")
        response = self._read_until_response("RES:", timeout=10.0)

        if not response:
            raise RuntimeError("No response from resistance test")

        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")

        # Parse response: RES:PASS:ADC:800:CAL:820:MOHM:50:OHM:0.050
        parts = response.split(":")

        passed = parts[1] == "PASS"
        adc_idx = parts.index("ADC")
        adc_value = int(parts[adc_idx + 1])

        # Check for calibration data
        calibrated = "CAL" in parts
        cal_adc = None
        milliohms = None
        ohms = None

        if calibrated:
            cal_idx = parts.index("CAL")
            cal_adc = int(parts[cal_idx + 1])

            if "MOHM" in parts:
                mohm_idx = parts.index("MOHM")
                milliohms = int(parts[mohm_idx + 1])

            if "OHM" in parts:
                ohm_idx = parts.index("OHM")
                ohm_str = parts[ohm_idx + 1]
                if ohm_str != "UNCAL":
                    ohms = float(ohm_str)

        return ResistanceResult(
            passed=passed,
            adc_value=adc_value,
            calibrated=calibrated,
            calibration_adc=cal_adc,
            milliohms=milliohms,
            ohms=ohms
        )

    def calibrate(self) -> CalibrationResult:
        """
        Calibrate resistance measurement with zero-ohm reference cable

        Returns:
            CalibrationResult with calibration outcome

        Response format: CAL:OK:ADC:xxx
        """
        if not self.connected:
            raise RuntimeError("Cable tester not connected")

        self._send_command("CAL")

        # Wait for "CAL:MEASURING..." then "CAL:OK:..."
        response = self._read_until_response("CAL:OK", timeout=15.0)

        if not response:
            return CalibrationResult(success=False, error="No response from calibration")

        if response.startswith("ERROR:"):
            return CalibrationResult(success=False, error=response)

        # Parse: CAL:OK:ADC:xxx
        parts = response.split(":")
        adc_idx = parts.index("ADC")
        adc_value = int(parts[adc_idx + 1])

        return CalibrationResult(success=True, adc_value=adc_value)

    def reset(self) -> bool:
        """Reset the test circuit"""
        if not self.connected:
            return False

        self._send_command("RESET")
        response = self._read_until_response("OK:", timeout=5.0)
        return response == "OK:RESET"

    def get_status(self) -> Dict[str, Any]:
        """Get tester status"""
        status = {
            'connected': self.connected,
            'port': self.port,
            'tester_id': self.tester_id,
            'ready': False
        }

        if self.connected:
            try:
                self._send_command("STATUS")
                response = self._read_until_response("STATUS:", timeout=5.0)
                if response:
                    parts = response.split(":")
                    status['ready'] = parts[1] == "READY"
                    status['status_response'] = response
            except Exception as e:
                status['error'] = str(e)

        return status

    def is_ready(self) -> bool:
        """Check if tester is ready"""
        if not self.connected:
            return False

        status = self.get_status()
        return status.get('ready', False)

    def close(self) -> None:
        """Close serial connection"""
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
            except:
                pass

        self.serial = None
        self.connected = False
        logger.info("Cable tester connection closed")


class MockCableTester(CableTesterInterface):
    """Mock cable tester for testing without hardware"""

    def __init__(self):
        self.connected = False
        self.calibrated = False
        self.calibration_adc = 820
        logger.info("Mock cable tester initialized")

    def initialize(self) -> bool:
        self.connected = True
        logger.info("Mock cable tester: Simulating initialization")
        return True

    def run_continuity_test(self) -> ContinuityResult:
        logger.info("Mock cable tester: Simulating continuity test - PASS")
        return ContinuityResult(
            passed=True,
            tip_to_tip=True,
            tip_to_sleeve=False,
            sleeve_to_sleeve=True,
            sleeve_to_tip=False,
            reason=None
        )

    def run_resistance_test(self) -> ResistanceResult:
        logger.info("Mock cable tester: Simulating resistance test - PASS")
        return ResistanceResult(
            passed=True,
            adc_value=800,
            calibrated=self.calibrated,
            calibration_adc=self.calibration_adc if self.calibrated else None,
            milliohms=50 if self.calibrated else None,
            ohms=0.050 if self.calibrated else None
        )

    def calibrate(self) -> CalibrationResult:
        logger.info("Mock cable tester: Simulating calibration")
        self.calibrated = True
        return CalibrationResult(success=True, adc_value=self.calibration_adc)

    def get_status(self) -> Dict[str, Any]:
        return {
            'connected': self.connected,
            'port': 'MOCK',
            'tester_id': 'MOCK_TESTER',
            'ready': self.connected,
            'mock': True
        }

    def is_ready(self) -> bool:
        return self.connected

    def close(self) -> None:
        self.connected = False
        logger.info("Mock cable tester: Connection closed")
