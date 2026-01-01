"""
TSC TE210 Label Printer Implementation

Implements the LabelPrinterInterface for TSC TE210 thermal transfer printer
using TSPL (TSC Printer Language) commands over raw socket connection.

Label size: 1" x 3" (25.4mm x 76.2mm)
Communication: TCP/IP socket on port 9100
"""

import socket
import logging
from typing import Dict, Any, Optional
from greenlight.hardware.interfaces import LabelPrinterInterface, PrintJob

logger = logging.getLogger(__name__)


class TSCLabelPrinter(LabelPrinterInterface):
    """TSC TE210 thermal transfer label printer"""

    def __init__(self, ip_address: str, port: int = 9100,
                 label_width_mm: float = 76.2, label_height_mm: float = 25.4):
        """
        Initialize TSC label printer

        Args:
            ip_address: IP address of the printer
            port: TCP port (default 9100 for raw printing)
            label_width_mm: Label width in millimeters (default 76.2mm = 3")
            label_height_mm: Label height in millimeters (default 25.4mm = 1")
        """
        self.ip_address = ip_address
        self.port = port
        self.label_width_mm = label_width_mm
        self.label_height_mm = label_height_mm
        self.connected = False
        self.socket: Optional[socket.socket] = None

        # Convert mm to dots (203 DPI for TE210)
        self.dpi = 203
        self.label_width_dots = int(label_width_mm * self.dpi / 25.4)
        self.label_height_dots = int(label_height_mm * self.dpi / 25.4)

        logger.info(f"TSC Printer configured: {ip_address}:{port}, "
                   f"Label: {label_width_mm}x{label_height_mm}mm "
                   f"({self.label_width_dots}x{self.label_height_dots} dots)")

    def initialize(self) -> bool:
        """Initialize printer connection"""
        try:
            # Test connection with short timeout for fast startup
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(2.0)  # Reduced from 5.0 to 2.0 for faster startup
            test_socket.connect((self.ip_address, self.port))

            # Don't wait for response - just test if we can connect
            test_socket.close()
            self.connected = True
            logger.info(f"TSC printer initialized at {self.ip_address}:{self.port}")
            return True

        except (socket.timeout, socket.error, OSError) as e:
            logger.error(f"Failed to initialize TSC printer: {e}")
            self.connected = False
            return False

    def _send_tspl_commands(self, commands: str) -> bool:
        """
        Send TSPL commands to printer

        Args:
            commands: TSPL command string

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create fresh socket for each print job
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((self.ip_address, self.port))

            # Send commands
            bytes_sent = sock.sendall(commands.encode('utf-8'))

            # Close socket
            sock.close()

            logger.info(f"Sent {len(commands)} bytes to printer at {self.ip_address}")
            logger.debug(f"TSPL commands:\n{commands}")
            return True

        except (socket.timeout, socket.error, OSError) as e:
            logger.error(f"Failed to send TSPL commands: {e}")
            return False

    def print_labels(self, print_job: PrintJob) -> bool:
        """
        Print cable labels

        Args:
            print_job: PrintJob with template and data

        Returns:
            True if successful, False otherwise
        """
        if not self.connected and not self.initialize():
            logger.error("Printer not connected and initialization failed")
            return False

        try:
            # Generate TSPL commands based on template
            if print_job.template == "cable_label":
                tspl = self._generate_cable_label_tspl(print_job.data)
            else:
                logger.error(f"Unknown template: {print_job.template}")
                return False

            # Send commands to printer
            success = self._send_tspl_commands(tspl)

            if success:
                logger.info(f"Successfully printed {print_job.quantity} label(s)")

            return success

        except Exception as e:
            logger.error(f"Error printing labels: {e}")
            return False

    def _generate_cable_label_tspl(self, data: Dict[str, Any]) -> str:
        """
        Generate TSPL commands for cable label

        Label layout (1" x 3"):
        +----------------------------------+
        | SUNDIAL AUDIO     [Logo]         |
        |                                  |
        | Studio Series                    |
        | 20' Goldline                     |
        | Straight Connectors    SC-20GL   |
        +----------------------------------+

        Args:
            data: Dictionary with cable information:
                - series: Cable series (e.g., "Studio Series")
                - length: Cable length (e.g., "20")
                - color_pattern: Color/pattern (e.g., "Goldline")
                - connector_type: Connector type (e.g., "Straight")
                - sku: SKU code (e.g., "SC-20GL")
                - description: Optional custom description for MISC cables

        Returns:
            TSPL command string
        """
        # Extract data
        series = data.get('series', 'Unknown')
        length = data.get('length', '?')
        # Convert length to string and handle floats (database returns REAL/float)
        if isinstance(length, (int, float)):
            # Format as integer if it's a whole number (20.0 -> 20)
            length = str(int(length)) if length == int(length) else str(length)
        color_pattern = data.get('color_pattern', 'Unknown')
        connector_type = data.get('connector_type', 'Unknown')
        sku = data.get('sku', 'UNKNOWN')
        description = data.get('description')

        # Format connector type for display
        connector_display = self._format_connector_type(connector_type)

        # Check if this is a MISC cable with custom description
        is_misc = sku.endswith('-MISC')

        # Start TSPL commands
        tspl_commands = []

        # Set label size (width, height in mm)
        tspl_commands.append(f"SIZE {self.label_width_mm:.1f} mm, {self.label_height_mm:.1f} mm")

        # Set printing gap (gap between labels, offset from edge)
        # Gap of 2-3mm works well, with 2mm offset to prevent first label cutoff
        tspl_commands.append("GAP 2 mm, 2 mm")

        # Set printing direction and origin
        tspl_commands.append("DIRECTION 1,0")  # Normal orientation
        tspl_commands.append("REFERENCE 0,0")  # Set reference point

        # Calibrate sensor before printing (helps with alignment)
        tspl_commands.append("SET TEAR ON")
        tspl_commands.append("SET PEEL OFF")

        # Clear image buffer
        tspl_commands.append("CLS")

        # Set print density (0-15, where 8 is medium)
        tspl_commands.append("DENSITY 10")

        # Set print speed (2-4 inches/sec, where 4 is slower/better quality)
        tspl_commands.append("SPEED 3")

        # Y positions (from top, in dots at 203 DPI)
        # Label is 1" tall = ~203 dots
        # Add more top margin to prevent cutoff
        y_brand = 20      # SUNDIAL AUDIO at top (moved down from 10)
        y_series = 70     # Series name (moved down from 60)
        y_length = 105    # Length and color/pattern (moved down from 95)
        y_connector = 140 # Connector type and SKU (moved down from 130)
        y_misc_desc = 175 # For MISC description (moved down from 165)

        # X positions (from left, in dots)
        # Label is 3" wide = ~609 dots
        # Increase left margin from 10 to 20 dots
        x_left = 20
        # For right-aligned text, calculate based on estimated text width
        # Font "2" is approximately 12 dots wide per character at normal scale
        # SKU is typically 6-8 characters, so reserve ~100 dots
        # Label width is ~609 dots, so position SKU to prevent cutoff
        x_sku = 450  # SKU position (adjusted to prevent cutoff)

        # Line 1: SUNDIAL AUDIO (brand)
        tspl_commands.append(f'TEXT {x_left},{y_brand},"3",0,1,1,"SUNDIAL"')
        tspl_commands.append(f'TEXT {x_left + 180},{y_brand},"3",0,1,1,"AUDIO"')

        # Add small decorative line under brand
        tspl_commands.append(f'BAR {x_left},{y_brand + 30},250,2')

        # Line 2: Series name
        tspl_commands.append(f'TEXT {x_left},{y_series},"2",0,1,1,"{series}"')

        # Line 3: Length and Color/Pattern
        if is_misc and description:
            # For MISC cables, show custom description
            # Split description if it's too long
            desc_parts = self._split_text(description, max_length=35)
            length_text = f"{length}'"
            tspl_commands.append(f'TEXT {x_left},{y_length},"2",0,1,1,"{length_text}"')

            # Add description on next line(s)
            for i, part in enumerate(desc_parts[:2]):  # Max 2 lines
                tspl_commands.append(f'TEXT {x_left},{y_connector + (i * 30)},"1",0,1,1,"{part}"')
        else:
            # Normal cable: show length and color pattern
            length_text = f"{length}' {color_pattern}"
            tspl_commands.append(f'TEXT {x_left},{y_length},"2",0,1,1,"{length_text}"')

            # Line 4: Connector type
            tspl_commands.append(f'TEXT {x_left},{y_connector},"1",0,1,1,"{connector_display}"')

        # SKU (right side on connector line)
        tspl_commands.append(f'TEXT {x_sku},{y_connector},"2",0,1,1,"{sku}"')

        # Print the label
        tspl_commands.append("PRINT 1")  # Print 1 copy
        tspl_commands.append("")  # Blank line to ensure command is processed

        # Join all commands with CRLF
        return '\r\n'.join(tspl_commands) + '\r\n'

    def _format_connector_type(self, connector_type: str) -> str:
        """Format connector type for display on label"""
        # Map connector types to display text
        connector_map = {
            'TS-TS': 'Straight TS',
            'TRS-TRS': 'Straight TRS',
            'TS-TRS': 'TS to TRS',
            'XLR-XLR': 'XLR to XLR',
            'XLR-TRS': 'XLR to TRS',
            'Straight': 'Straight Connectors',
            'Right Angle': 'Right Angle',
        }
        return connector_map.get(connector_type, connector_type)

    def _split_text(self, text: str, max_length: int) -> list:
        """Split text into multiple lines if too long"""
        if len(text) <= max_length:
            return [text]

        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            if len(current_line) + len(word) + 1 <= max_length:
                current_line += (" " if current_line else "") + word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines

    def get_status(self) -> Dict[str, Any]:
        """Get printer status"""
        status = {
            'connected': self.connected,
            'ip_address': self.ip_address,
            'port': self.port,
            'label_size': f"{self.label_width_mm}x{self.label_height_mm}mm",
            'ready': self.is_ready()
        }

        # Try to get detailed status from printer
        if self.connected:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((self.ip_address, self.port))

                # Request status (~!T command)
                sock.sendall(b'~!T\r\n')

                # Read response (if any)
                sock.settimeout(1.0)
                try:
                    response = sock.recv(256)
                    status['printer_response'] = response.decode('utf-8', errors='ignore').strip()
                except socket.timeout:
                    pass

                sock.close()

            except (socket.error, OSError) as e:
                status['status_error'] = str(e)

        return status

    def is_ready(self) -> bool:
        """Check if printer is ready to print"""
        if not self.connected:
            # Try to reconnect
            return self.initialize()

        try:
            # Quick connection test
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((self.ip_address, self.port))
            sock.close()
            return True
        except (socket.timeout, socket.error, OSError):
            self.connected = False
            return False

    def close(self) -> None:
        """Close printer connection"""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        self.connected = False
        logger.info("TSC printer connection closed")


class MockTSCLabelPrinter(LabelPrinterInterface):
    """Mock TSC label printer for testing without hardware"""

    def __init__(self, ip_address: str = "192.168.0.52", port: int = 9100):
        self.ip_address = ip_address
        self.port = port
        self.connected = False
        logger.info(f"Mock TSC printer initialized (no actual hardware)")

    def initialize(self) -> bool:
        """Mock initialization"""
        logger.info("Mock TSC printer: Simulating initialization")
        self.connected = True
        return True

    def print_labels(self, print_job: PrintJob) -> bool:
        """Mock label printing"""
        logger.info(f"Mock TSC printer: Would print {print_job.quantity} label(s)")
        logger.info(f"  Template: {print_job.template}")
        logger.info(f"  Data: {print_job.data}")

        # Simulate TSPL generation
        if print_job.template == "cable_label":
            logger.debug("Mock TSPL commands would be generated here")

        return True

    def get_status(self) -> Dict[str, Any]:
        """Mock status"""
        return {
            'connected': self.connected,
            'ip_address': self.ip_address,
            'port': self.port,
            'mock': True,
            'ready': True
        }

    def is_ready(self) -> bool:
        """Mock ready check"""
        return self.connected

    def close(self) -> None:
        """Mock close"""
        self.connected = False
        logger.info("Mock TSC printer: Connection closed")
