"""
Arduino Cable Tester Interface

Supports two communication backends:
  - ArduinoCableTester: USB serial (Pi + Mega 2560)
  - BridgeCableTester: Router Bridge msgpack-rpc (UNO Q)

Both use the same text-based command/response protocol from the MCU.
Commands: CONT, RES, CAL, XCONT, XSHELL, XRES, XCAL, STATUS, ID, RESET
"""

import serial
import serial.tools.list_ports
import logging
import time
import socket
import threading
from typing import Dict, Any, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ===== Result dataclasses =====

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


@dataclass
class XlrContinuityResult:
    """Result from XLR continuity test (3x3 pin matrix)"""
    passed: bool
    matrix: Dict[str, bool]  # P11..P33 → bool
    reason: Optional[str] = None


@dataclass
class XlrShellResult:
    """Result from XLR shell bond test"""
    passed: bool
    near_shell_bond: bool
    far_shell_bond: bool
    shell_to_shell: bool
    reason: Optional[str] = None


@dataclass
class XlrResistanceResult:
    """Result from XLR resistance test (per-pin)"""
    passed: bool
    pin2_adc: int
    pin3_adc: int
    calibrated: bool
    pin2_cal_adc: Optional[int] = None
    pin3_cal_adc: Optional[int] = None
    pin2_milliohms: Optional[int] = None
    pin2_ohms: Optional[float] = None
    pin3_milliohms: Optional[int] = None
    pin3_ohms: Optional[float] = None


@dataclass
class XlrCalibrationResult:
    """Result from XLR calibration"""
    success: bool
    pin2_adc: Optional[int] = None
    pin3_adc: Optional[int] = None
    error: Optional[str] = None


# ===== Shared response parsers =====
# Both ArduinoCableTester (serial) and BridgeCableTester (rpc) get the same
# colon-delimited response strings from the MCU. These functions parse them.

def parse_continuity_response(response: str) -> ContinuityResult:
    """Parse: RESULT:PASS/FAIL:TT:x:TS:x:SS:x:ST:x[:REASON:xxx]"""
    parts = response.split(":")

    passed = parts[1] == "PASS"
    tt = int(parts[3]) == 1
    ts = int(parts[5]) == 1
    ss = int(parts[7]) == 1
    st = int(parts[9]) == 1

    reason = None
    if "REASON" in parts:
        reason = parts[parts.index("REASON") + 1]

    return ContinuityResult(
        passed=passed, tip_to_tip=tt, tip_to_sleeve=ts,
        sleeve_to_sleeve=ss, sleeve_to_tip=st, reason=reason
    )


def parse_resistance_response(response: str) -> ResistanceResult:
    """Parse: RES:PASS/FAIL:ADC:xxx[:CAL:xxx:MOHM:xxx:OHM:xxx]"""
    parts = response.split(":")

    passed = parts[1] == "PASS"
    adc_value = int(parts[parts.index("ADC") + 1])

    calibrated = "CAL" in parts
    cal_adc = None
    milliohms = None
    ohms = None

    if calibrated:
        cal_adc = int(parts[parts.index("CAL") + 1])
        if "MOHM" in parts:
            milliohms = int(parts[parts.index("MOHM") + 1])
        if "OHM" in parts:
            ohm_str = parts[parts.index("OHM") + 1]
            if ohm_str != "UNCAL":
                ohms = float(ohm_str)

    return ResistanceResult(
        passed=passed, adc_value=adc_value, calibrated=calibrated,
        calibration_adc=cal_adc, milliohms=milliohms, ohms=ohms
    )


def parse_calibration_response(response: str) -> CalibrationResult:
    """Parse: CAL:OK:ADC:xxx or CAL:FAIL:..."""
    if response.startswith("CAL:FAIL") or response.startswith("ERROR:"):
        return CalibrationResult(success=False, error=response)

    parts = response.split(":")
    adc_value = int(parts[parts.index("ADC") + 1])
    return CalibrationResult(success=True, adc_value=adc_value)


def parse_xlr_continuity_response(response: str) -> XlrContinuityResult:
    """Parse: XCONT:PASS/FAIL:P11:x:P12:x:...:P33:x[:REASON:xxx]"""
    parts = response.split(":")
    passed = parts[1] == "PASS"

    matrix = {}
    for d in range(1, 4):
        for s in range(1, 4):
            key = f"P{d}{s}"
            matrix[key] = int(parts[parts.index(key) + 1]) == 1

    reason = None
    if "REASON" in parts:
        reason = parts[parts.index("REASON") + 1]

    return XlrContinuityResult(passed=passed, matrix=matrix, reason=reason)


def parse_xlr_shell_response(response: str) -> XlrShellResult:
    """Parse: XSHELL:PASS/FAIL:NEAR:x:FAR:x:SS:x[:REASON:xxx]"""
    parts = response.split(":")
    passed = parts[1] == "PASS"

    near = int(parts[parts.index("NEAR") + 1]) == 1
    far = int(parts[parts.index("FAR") + 1]) == 1
    ss = int(parts[parts.index("SS") + 1]) == 1

    reason = None
    if "REASON" in parts:
        reason = parts[parts.index("REASON") + 1]

    return XlrShellResult(
        passed=passed, near_shell_bond=near, far_shell_bond=far,
        shell_to_shell=ss, reason=reason
    )


def parse_xlr_resistance_response(response: str) -> XlrResistanceResult:
    """Parse: XRES:PASS/FAIL:P2ADC:x:P3ADC:x[:P2CAL:x:P3CAL:x:P2MOHM:x:P2OHM:x:P3MOHM:x:P3OHM:x]"""
    parts = response.split(":")
    passed = parts[1] == "PASS"

    pin2_adc = int(parts[parts.index("P2ADC") + 1])
    pin3_adc = int(parts[parts.index("P3ADC") + 1])

    calibrated = "P2CAL" in parts
    pin2_cal = pin3_cal = pin2_mohm = pin2_ohm = pin3_mohm = pin3_ohm = None

    if calibrated:
        pin2_cal = int(parts[parts.index("P2CAL") + 1])
        pin3_cal = int(parts[parts.index("P3CAL") + 1])
        if "P2MOHM" in parts:
            pin2_mohm = int(parts[parts.index("P2MOHM") + 1])
        if "P2OHM" in parts:
            pin2_ohm = float(parts[parts.index("P2OHM") + 1])
        if "P3MOHM" in parts:
            pin3_mohm = int(parts[parts.index("P3MOHM") + 1])
        if "P3OHM" in parts:
            pin3_ohm = float(parts[parts.index("P3OHM") + 1])

    return XlrResistanceResult(
        passed=passed, pin2_adc=pin2_adc, pin3_adc=pin3_adc,
        calibrated=calibrated, pin2_cal_adc=pin2_cal, pin3_cal_adc=pin3_cal,
        pin2_milliohms=pin2_mohm, pin2_ohms=pin2_ohm,
        pin3_milliohms=pin3_mohm, pin3_ohms=pin3_ohm
    )


def parse_xlr_calibration_response(response: str) -> XlrCalibrationResult:
    """Parse: XCAL:OK:P2ADC:x:P3ADC:x or XCAL:FAIL:..."""
    parts = response.split(":")

    if response.startswith("XCAL:FAIL") or response.startswith("ERROR:"):
        error_msg = "Calibration failed"
        if "NO_CABLE" in parts:
            error_msg = "No cable detected"
        p2adc = int(parts[parts.index("P2ADC") + 1]) if "P2ADC" in parts else None
        p3adc = int(parts[parts.index("P3ADC") + 1]) if "P3ADC" in parts else None
        return XlrCalibrationResult(success=False, pin2_adc=p2adc, pin3_adc=p3adc, error=error_msg)

    pin2_adc = int(parts[parts.index("P2ADC") + 1])
    pin3_adc = int(parts[parts.index("P3ADC") + 1])
    return XlrCalibrationResult(success=True, pin2_adc=pin2_adc, pin3_adc=pin3_adc)


# ===== Abstract interface =====

class CableTesterInterface(ABC):
    """Abstract interface for cable testers"""

    @abstractmethod
    def initialize(self) -> bool:
        pass

    @abstractmethod
    def run_continuity_test(self) -> ContinuityResult:
        pass

    @abstractmethod
    def run_resistance_test(self) -> ResistanceResult:
        pass

    @abstractmethod
    def calibrate(self) -> CalibrationResult:
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


# ===== Serial implementation (Pi + Mega 2560) =====

class ArduinoCableTester(CableTesterInterface):
    """Arduino Mega 2560 cable tester via USB serial"""

    def __init__(self, port: Optional[str] = None, baudrate: int = 9600, timeout: float = 5.0):
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
            if 'ttyACM' in port.device or 'Arduino' in (port.description or ''):
                logger.info(f"Found Arduino at {port.device}: {port.description}")
                return port.device
            if 'ttyUSB' in port.device:
                logger.info(f"Found potential Arduino at {port.device}: {port.description}")
                return port.device
        return None

    def initialize(self) -> bool:
        """Initialize connection to Arduino cable tester"""
        try:
            if self.port is None:
                self.port = self._find_arduino_port()
                if self.port is None:
                    logger.error("No Arduino cable tester found")
                    return False

            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout
            )

            time.sleep(2.0)
            self.serial.reset_input_buffer()

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
        if not self.serial or not self.serial.is_open:
            raise RuntimeError("Serial connection not open")
        self.serial.write(f"{command}\n".encode('utf-8'))
        self.serial.flush()
        logger.debug(f"Sent: {command}")

    def _read_response(self, timeout: Optional[float] = None) -> Optional[str]:
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
                    logger.debug(f"Skipping: {response}")
        return None

    def _command_and_parse(self, command: str, prefix: str, timeout: float = 10.0) -> str:
        """Send command, wait for response with prefix, raise on error/timeout"""
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        self._send_command(command)
        response = self._read_until_response(prefix, timeout=timeout)
        if not response:
            raise RuntimeError(f"No response from {command}")
        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")
        return response

    def run_continuity_test(self) -> ContinuityResult:
        return parse_continuity_response(
            self._command_and_parse("CONT", "RESULT:"))

    def run_resistance_test(self) -> ResistanceResult:
        return parse_resistance_response(
            self._command_and_parse("RES", "RES:"))

    def calibrate(self) -> CalibrationResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        self._send_command("CAL")
        response = self._read_until_response("CAL:OK", timeout=15.0)
        if not response:
            return CalibrationResult(success=False, error="No response from calibration")
        if response.startswith("ERROR:"):
            return CalibrationResult(success=False, error=response)
        return parse_calibration_response(response)

    def run_xlr_continuity_test(self) -> XlrContinuityResult:
        return parse_xlr_continuity_response(
            self._command_and_parse("XCONT", "XCONT:"))

    def run_xlr_shell_test(self) -> XlrShellResult:
        return parse_xlr_shell_response(
            self._command_and_parse("XSHELL", "XSHELL:"))

    def run_xlr_resistance_test(self) -> XlrResistanceResult:
        return parse_xlr_resistance_response(
            self._command_and_parse("XRES", "XRES:"))

    def xlr_calibrate(self) -> XlrCalibrationResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        self._send_command("XCAL")
        start_time = time.time()
        response = None
        while time.time() - start_time < 15.0:
            line = self._read_response(timeout=0.5)
            if line:
                if line.startswith("XCAL:OK") or line.startswith("XCAL:FAIL"):
                    response = line
                    break
                elif line.startswith("ERROR:"):
                    return XlrCalibrationResult(success=False, error=line)
                else:
                    logger.debug(f"Skipping: {line}")
        if not response:
            return XlrCalibrationResult(success=False, error="No response from XLR calibration")
        return parse_xlr_calibration_response(response)

    def reset(self) -> bool:
        if not self.connected:
            return False
        self._send_command("RESET")
        response = self._read_until_response("OK:", timeout=5.0)
        return response == "OK:RESET"

    def get_status(self) -> Dict[str, Any]:
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
        if not self.connected:
            return False
        return self.get_status().get('ready', False)

    def close(self) -> None:
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
            except:
                pass
        self.serial = None
        self.connected = False
        logger.info("Cable tester connection closed")


# ===== Router Bridge implementation (UNO Q) =====

ROUTER_SOCKET_PATH = "/var/run/arduino-router.sock"

class BridgeCableTester(CableTesterInterface):
    """UNO Q cable tester via Router Bridge (msgpack-rpc over unix socket)

    The MCU sketch exposes a single run_command(cmd) function via the Router Bridge.
    It accepts the same command strings (CONT, RES, CAL, etc.) and returns the same
    colon-delimited response strings as the serial version.
    """

    def __init__(self, socket_path: str = ROUTER_SOCKET_PATH):
        self.socket_path = socket_path
        self.connected = False
        self.tester_id: Optional[str] = None
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._next_msgid = 0

    def _connect(self) -> bool:
        """Connect to the arduino-router unix socket"""
        try:
            import msgpack  # noqa: F811
        except ImportError:
            logger.error("msgpack package required for Bridge communication: pip install msgpack")
            return False

        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(self.socket_path)
            self._sock.settimeout(15.0)
            return True
        except OSError as e:
            logger.error(f"Failed to connect to router socket: {e}")
            self._sock = None
            return False

    def _rpc_call(self, method: str, *params, timeout: float = 15.0) -> Any:
        """Send msgpack-rpc call and return result"""
        import msgpack

        with self._lock:
            self._next_msgid += 1
            msgid = self._next_msgid

            request = [0, msgid, method, list(params)]
            self._sock.sendall(msgpack.packb(request))

            old_timeout = self._sock.gettimeout()
            self._sock.settimeout(timeout)
            try:
                unpacker = msgpack.Unpacker()
                while True:
                    data = self._sock.recv(4096)
                    if not data:
                        raise RuntimeError("Router connection closed")
                    unpacker.feed(data)
                    for msg in unpacker:
                        if not isinstance(msg, list) or len(msg) < 4:
                            continue
                        msg_type, resp_msgid, error, result = msg[0], msg[1], msg[2], msg[3]
                        if msg_type == 1 and resp_msgid == msgid:
                            if error is not None:
                                raise RuntimeError(f"RPC error: {error}")
                            return result
            finally:
                self._sock.settimeout(old_timeout)

    def _run_command(self, command: str, timeout: float = 15.0) -> str:
        """Send command to MCU via Bridge and return response string"""
        result = self._rpc_call("run_command", command, timeout=timeout)
        if isinstance(result, bytes):
            result = result.decode('utf-8')
        logger.debug(f"Bridge command '{command}' -> '{result}'")
        return result

    def initialize(self) -> bool:
        """Initialize Bridge connection and verify MCU is responding"""
        try:
            if not self._connect():
                return False

            response = self._run_command("ID")
            if response and response.startswith("ID:"):
                self.tester_id = response.split(":")[1]
                self.connected = True
                logger.info(f"Bridge cable tester initialized: {self.tester_id}")
                return True
            else:
                logger.error(f"Unexpected response from Bridge cable tester: {response}")
                self.close()
                return False

        except Exception as e:
            logger.error(f"Failed to initialize Bridge cable tester: {e}")
            self.connected = False
            return False

    def run_continuity_test(self) -> ContinuityResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("CONT")
        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")
        return parse_continuity_response(response)

    def run_resistance_test(self) -> ResistanceResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("RES")
        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")
        return parse_resistance_response(response)

    def calibrate(self) -> CalibrationResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("CAL", timeout=20.0)
        if response.startswith("ERROR:"):
            return CalibrationResult(success=False, error=response)
        return parse_calibration_response(response)

    def run_xlr_continuity_test(self) -> XlrContinuityResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("XCONT")
        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")
        return parse_xlr_continuity_response(response)

    def run_xlr_shell_test(self) -> XlrShellResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("XSHELL")
        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")
        return parse_xlr_shell_response(response)

    def run_xlr_resistance_test(self) -> XlrResistanceResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("XRES")
        if response.startswith("ERROR:"):
            raise RuntimeError(f"Tester error: {response}")
        return parse_xlr_resistance_response(response)

    def xlr_calibrate(self) -> XlrCalibrationResult:
        if not self.connected:
            raise RuntimeError("Cable tester not connected")
        response = self._run_command("XCAL", timeout=20.0)
        if response.startswith("ERROR:"):
            return XlrCalibrationResult(success=False, error=response)
        return parse_xlr_calibration_response(response)

    def reset(self) -> bool:
        if not self.connected:
            return False
        response = self._run_command("RESET")
        return response == "OK:RESET"

    def get_status(self) -> Dict[str, Any]:
        status = {
            'connected': self.connected,
            'port': 'bridge:' + self.socket_path,
            'tester_id': self.tester_id,
            'ready': False
        }
        if self.connected:
            try:
                response = self._run_command("STATUS")
                if response:
                    parts = response.split(":")
                    status['ready'] = parts[1] == "READY"
                    status['status_response'] = response
            except Exception as e:
                status['error'] = str(e)
        return status

    def is_ready(self) -> bool:
        if not self.connected:
            return False
        return self.get_status().get('ready', False)

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except:
                pass
        self._sock = None
        self.connected = False
        logger.info("Bridge cable tester connection closed")


# ===== Mock implementation =====

class MockCableTester(CableTesterInterface):
    """Mock cable tester for testing without hardware"""

    def __init__(self):
        self.connected = False
        self.calibrated = False
        self.xlr_calibrated = False
        self.calibration_adc = 60
        self.xlr_calibration_p2 = 58
        self.xlr_calibration_p3 = 62
        logger.info("Mock cable tester initialized")

    def initialize(self) -> bool:
        self.connected = True
        logger.info("Mock cable tester: Simulating initialization")
        return True

    def run_continuity_test(self) -> ContinuityResult:
        logger.info("Mock cable tester: Simulating continuity test - PASS")
        return ContinuityResult(
            passed=True, tip_to_tip=True, tip_to_sleeve=False,
            sleeve_to_sleeve=True, sleeve_to_tip=False, reason=None
        )

    def run_resistance_test(self) -> ResistanceResult:
        logger.info("Mock cable tester: Simulating resistance test - PASS")
        return ResistanceResult(
            passed=True, adc_value=65, calibrated=self.calibrated,
            calibration_adc=self.calibration_adc if self.calibrated else None,
            milliohms=50 if self.calibrated else None,
            ohms=0.050 if self.calibrated else None
        )

    def calibrate(self) -> CalibrationResult:
        logger.info("Mock cable tester: Simulating calibration")
        self.calibrated = True
        return CalibrationResult(success=True, adc_value=self.calibration_adc)

    def run_xlr_continuity_test(self) -> XlrContinuityResult:
        logger.info("Mock cable tester: Simulating XLR continuity test - PASS")
        matrix = {
            'P11': True, 'P12': False, 'P13': False,
            'P21': False, 'P22': True, 'P23': False,
            'P31': False, 'P32': False, 'P33': True,
        }
        return XlrContinuityResult(passed=True, matrix=matrix, reason=None)

    def run_xlr_shell_test(self) -> XlrShellResult:
        logger.info("Mock cable tester: Simulating XLR shell test - PASS")
        return XlrShellResult(
            passed=True, near_shell_bond=True, far_shell_bond=True,
            shell_to_shell=True, reason=None
        )

    def run_xlr_resistance_test(self) -> XlrResistanceResult:
        logger.info("Mock cable tester: Simulating XLR resistance test - PASS")
        return XlrResistanceResult(
            passed=True, pin2_adc=65, pin3_adc=68,
            calibrated=self.xlr_calibrated,
            pin2_cal_adc=self.xlr_calibration_p2 if self.xlr_calibrated else None,
            pin3_cal_adc=self.xlr_calibration_p3 if self.xlr_calibrated else None,
            pin2_milliohms=50 if self.xlr_calibrated else None,
            pin2_ohms=0.050 if self.xlr_calibrated else None,
            pin3_milliohms=60 if self.xlr_calibrated else None,
            pin3_ohms=0.060 if self.xlr_calibrated else None
        )

    def xlr_calibrate(self) -> XlrCalibrationResult:
        logger.info("Mock cable tester: Simulating XLR calibration")
        self.xlr_calibrated = True
        return XlrCalibrationResult(
            success=True,
            pin2_adc=self.xlr_calibration_p2,
            pin3_adc=self.xlr_calibration_p3
        )

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
