"""
TSC TE210 Label Printer Implementation

Implements the LabelPrinterInterface for TSC TE210 thermal transfer printer
using TSPL (TSC Printer Language) commands over raw socket connection.

Label size: 1" x 3" (25.4mm x 76.2mm)
Communication: TCP/IP socket on port 9100
"""

import socket
import logging
import struct
import io
from typing import Dict, Any, Optional
from greenlight.hardware.interfaces import LabelPrinterInterface, PrintJob

logger = logging.getLogger(__name__)

# Wire logo bitmap (50x15 pixels, 1-bit BMP) - embedded to avoid file dependency
WIRE_LOGO_BMP_DATA = (
    b'BM\xfa\x00\x00\x00\x00\x00\x00\x00\x82\x00\x00\x00l\x00\x00\x002\x00\x00\x00'
    b'\x0f\x00\x00\x00\x01\x00\x01\x00\x00\x00\x00\x00x\x00\x00\x00\x13\x0b\x00\x00'
    b'\x13\x0b\x00\x00\x02\x00\x00\x00\x02\x00\x00\x00\x00\x00\xff\x00\x00\xff\x00'
    b'\x00\xff\x00\x00\x00\x00\x00\x00\xffBGRs\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    b'\x00\x00\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xc0\x00\xff\xe0\x07\xff\xff'
    b'\xff\xc0\x004\x00\x00\x7f\xf6\x02\xc0\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00'
    b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00 \x00\x00\x80\x00'
    b'\x00\x00\x00\x14\x00\x00\x00\x00\x00\x00\x00\xff\x90!.\x80\x00\x00\x00\xff\xfb'
    b'U\xff\xe0\x00\x00\x00\xff\xff\xff\xff\xff\xaf\xc0\x00\xff\xff\xff\xff\xff\xff'
    b'\xc0\x00\xff\xff\xff\xff\xff\xff\xc0\x00\xff\xff\xff\xff\xff\xff\xc0\x00\xff'
    b'\xff\xff\xff\xff\xff\xc0\x00'
)


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

        # Parse embedded wire logo bitmap
        self.wire_logo_data = self._parse_bitmap(WIRE_LOGO_BMP_DATA)

    def _parse_bitmap(self, data: bytes) -> Optional[Dict[str, Any]]:
        """Parse a 1-bit BMP and prepare it for inline BITMAP command."""
        try:
            if data[:2] != b'BM':
                logger.warning("Invalid BMP data: missing BM header")
                return None

            # Parse BMP header
            width = struct.unpack('<I', data[18:22])[0]
            height = struct.unpack('<I', data[22:26])[0]
            bpp = struct.unpack('<H', data[28:30])[0]
            data_offset = struct.unpack('<I', data[10:14])[0]

            if bpp != 1:
                logger.warning(f"Bitmap must be 1-bit, got {bpp}-bit")
                return None

            # Get pixel data (BMP stores rows bottom-to-top, need to flip)
            pixel_data = data[data_offset:]
            bytes_per_row = ((width + 31) // 32) * 4  # BMP row padding

            # Flip rows (BMP is bottom-up)
            rows = [pixel_data[i:i+bytes_per_row] for i in range(0, len(pixel_data), bytes_per_row)]
            rows.reverse()

            # TSPL BITMAP uses ceil(width/8) bytes per row, no padding
            # Crop 2 pixels off right edge to remove artifacts
            width = width - 2 if width > 8 else width
            tspl_bytes_per_row = (width + 7) // 8

            # Calculate mask for last byte to clear unused bits
            valid_bits_in_last_byte = width % 8
            if valid_bits_in_last_byte == 0:
                last_byte_mask = 0xFF
            else:
                last_byte_mask = (0xFF << (8 - valid_bits_in_last_byte)) & 0xFF

            # Build TSPL data, masking the last byte of each row
            tspl_rows = []
            for row in rows:
                row_data = bytearray(row[:tspl_bytes_per_row])
                if len(row_data) > 0:
                    row_data[-1] &= last_byte_mask  # Clear unused bits
                tspl_rows.append(bytes(row_data))
            tspl_data = b''.join(tspl_rows)

            logger.debug(f"Parsed wire logo bitmap: {width}x{height} pixels")
            return {
                'width': width,
                'height': height,
                'width_bytes': tspl_bytes_per_row,
                'data': tspl_data
            }
        except Exception as e:
            logger.error(f"Error parsing bitmap: {e}")
            return None

    def _get_bitmap_command(self, x: int, y: int) -> Optional[bytes]:
        """Generate TSPL BITMAP command for the wire logo."""
        if not self.wire_logo_data:
            return None

        d = self.wire_logo_data
        # BITMAP x,y,width_bytes,height,mode,data
        cmd = f'BITMAP {x},{y},{d["width_bytes"]},{d["height"]},0,'.encode()
        return cmd + d['data']

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

    def _send_tspl_commands(self, commands, bitmap_commands: list = None) -> bool:
        """
        Send TSPL commands to printer

        Args:
            commands: TSPL command string or bytes
            bitmap_commands: Optional list of (position_in_commands, bitmap_bytes) tuples

        Returns:
            True if successful, False otherwise
        """
        try:
            # Create fresh socket for each print job
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10.0)
            sock.connect((self.ip_address, self.port))

            # Convert string to bytes if needed
            if isinstance(commands, str):
                commands = commands.encode('utf-8')

            # Send commands
            sock.sendall(commands)

            # Close socket
            sock.close()

            logger.info(f"Sent {len(commands)} bytes to printer at {self.ip_address}")
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
            elif print_job.template == "registration_label":
                tspl = self._generate_registration_label_tspl(print_job.data)
            elif print_job.template == "wire_label":
                tspl = self._generate_wire_label_tspl(print_job.data)
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

    def _generate_cable_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """
        Generate TSPL commands for cable label

        Label layout (1" x 3"):
        +----------------------------------------------------+
        | SUNDIAL AUDIO                         QC: ADW      |
        | ────────────────                                   |
        | Studio Series                    ✓ Continuity      |
        | 20' Goldline                     ✓ Res < 0.5Ω      |
        | Straight TS              SC-20GL ✓ Capacitance     |
        +----------------------------------------------------+

        Args:
            data: Dictionary with cable information:
                - series: Cable series (e.g., "Studio Series")
                - length: Cable length (e.g., "20")
                - color_pattern: Color/pattern (e.g., "Goldline")
                - connector_type: Connector type (e.g., "Straight")
                - sku: SKU code (e.g., "SC-20GL")
                - description: Optional custom description for MISC cables
                - test_results: Optional dict with test info:
                    - continuity_pass: bool
                    - resistance_pass: bool
                    - operator: str (operator initials)

        Returns:
            TSPL commands as bytes (includes binary bitmap data)
        """
        # Extract data
        serial_number = data.get('serial_number', '')
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
        if description:
            # Strip redundant connector suffix from SKU descriptions
            description = description.replace(' and right angle plug', '')
            # Append tagline if it fits
            separator = '' if description[-1] in '.!?' else '.'
            tagline = f'Made with <3 in Florence, MA'
            if len(description) <= 35:
                # Description fits on line 1, put tagline on line 2
                description = description + separator + '\n' + tagline
            else:
                # Long description - try appending inline
                with_tagline = description + separator + ' ' + tagline
                parts = self._split_text(with_tagline, max_length=35)
                if len(parts) <= 2:
                    description = with_tagline
                elif len(parts) >= 3:
                    overflow = ' '.join(parts[2:])
                    if len(overflow) <= 55:
                        description = with_tagline

        # Extract test results if present
        test_results = data.get('test_results', {})
        has_test_results = bool(test_results)
        continuity_pass = test_results.get('continuity_pass', False)
        resistance_pass = test_results.get('resistance_pass', False)
        operator = test_results.get('operator', '')

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
        # Tighter spacing to fit all content
        y_brand = 8       # SUNDIAL AUDIO at top
        y_serial = 8      # Serial number (right side, same line as brand)
        y_sku_right = 30  # SKU under serial number on right
        y_series = 50     # Series name
        y_length = 82     # Length and color/pattern
        y_connector = 114 # Connector type
        y_sku = 146       # SKU at bottom left (for non-tested cables)
        y_misc_desc = 146 # For MISC description
        # QC results column - tighter spacing
        y_qc_con = 70     # CON result
        y_qc_res = 90     # RES result
        y_qc_date = 110   # Test date
        y_qc_op = 130     # QC operator

        # X positions (from left, in dots)
        # Label is 3" wide = ~609 dots
        # Increase left margin from 10 to 20 dots
        x_left = 20
        # For right-aligned text, calculate based on estimated text width
        # Font "2" is approximately 12 dots wide per character at normal scale
        # SKU is typically 6-8 characters, so reserve ~100 dots
        # Label width is ~609 dots, so position SKU to prevent cutoff
        x_sku = 450  # SKU position (adjusted to prevent cutoff)
        x_qc = 420   # QC results column on right side

        # Line 1: SUNDIAL [wire] AUDIO and serial number + SKU
        tspl_commands.append(f'TEXT {x_left},{y_brand},"3",0,1,1,"SUNDIAL"')
        # Wire logo between SUNDIAL and AUDIO - will be inserted as binary
        wire_logo_position = len(tspl_commands)  # Mark position for bitmap
        tspl_commands.append('__WIRE_LOGO__')  # Placeholder
        tspl_commands.append(f'TEXT {x_left + 190},{y_brand},"3",0,1,1,"AUDIO"')
        if serial_number:
            tspl_commands.append(f'TEXT {x_qc},{y_serial},"2",0,1,1,"#{serial_number}"')
        # SKU under serial number
        tspl_commands.append(f'TEXT {x_qc},{y_sku_right},"1",0,1,1,"{sku}"')

        # Add small decorative line under brand
        tspl_commands.append(f'BAR {x_left},{y_brand + 28},300,2')

        # Line 2: Series name
        tspl_commands.append(f'TEXT {x_left},{y_series},"2",0,1,1,"{series}"')

        # QC results in a tight column on the right (if tested)
        if has_test_results:
            cont_status = "PASS" if continuity_pass else "X"
            tspl_commands.append(f'TEXT {x_qc},{y_qc_con},"1",0,1,1,"CON: {cont_status}"')

        # Line 3: Length and Color/Pattern
        if is_misc:
            length_text = f"{length}' Special Baby"
        else:
            length_text = f"{length}' {color_pattern}"
        tspl_commands.append(f'TEXT {x_left},{y_length},"2",0,1,1,"{length_text}"')

        # Line 4+: Description (up to 3 lines, 3rd line full-width under QC column)
        if description:
            # Split on explicit newlines first, then word-wrap each segment
            if '\n' in description:
                desc_parts = description.split('\n')
            else:
                desc_parts = self._split_text(description, max_length=35)
                # Lines 1-2 at narrow width, line 3 merges any remaining text (full-width)
                final_parts = desc_parts[:2]
                if len(desc_parts) > 2:
                    final_parts.append(' '.join(desc_parts[2:]))
                desc_parts = final_parts
            for i, part in enumerate(desc_parts):
                y_desc = y_connector + (i * 24)
                tspl_commands.append(f'TEXT {x_left},{y_desc},"1",0,1,1,"{part}"')
        else:
            tspl_commands.append(f'TEXT {x_left},{y_connector},"1",0,1,1,"{connector_display}"')

        # Add resistance result
        if has_test_results:
            res_status = "PASS" if resistance_pass else "X"
            tspl_commands.append(f'TEXT {x_qc},{y_qc_res},"1",0,1,1,"RES: {res_status}"')

        # Test date
        if has_test_results:
            test_timestamp = test_results.get('test_timestamp')
            if test_timestamp:
                date_str = test_timestamp.strftime("%-m/%-d/%y %-I:%M%p").lower()
                tspl_commands.append(f'TEXT {x_qc},{y_qc_date},"1",0,1,1,"{date_str}"')

        # Operator at bottom of QC column
        if has_test_results and operator:
            tspl_commands.append(f'TEXT {x_qc},{y_qc_op},"1",0,1,1,"QC: {operator}"')

        # Print the label
        tspl_commands.append("PRINT 1")  # Print 1 copy
        tspl_commands.append("")  # Blank line to ensure command is processed

        # Build output as bytes, handling inline bitmap
        output = b''
        for cmd in tspl_commands:
            if cmd == '__WIRE_LOGO__':
                # Insert wire logo bitmap between SUNDIAL and AUDIO
                # Position: after SUNDIAL text (x_left + ~90 dots for "SUNDIAL"), same y as brand
                bitmap_cmd = self._get_bitmap_command(x_left + 120, y_brand + 2)
                if bitmap_cmd:
                    output += bitmap_cmd + b'\r\n'
                # Skip placeholder if no bitmap available
            else:
                output += cmd.encode('utf-8') + b'\r\n'

        return output

    def _generate_qr_bitmap(self, data: str, module_size: int = 3) -> Optional[bytes]:
        """Generate a QR code and convert to TSPL BITMAP format.

        Args:
            data: Data to encode in QR code
            module_size: Size of each QR module in dots (default 3)

        Returns:
            TSPL BITMAP command bytes, or None on error
        """
        try:
            import segno

            qr = segno.make(data, error='M')

            # Get the QR matrix (list of lists of bools)
            # Use buffer to get the raw matrix
            matrix = []
            buf = io.StringIO()
            qr.save(buf, kind='txt')
            buf.seek(0)
            for line in buf:
                line = line.rstrip('\n')
                if line:
                    row = [c == '1' for c in line]
                    matrix.append(row)

            if not matrix:
                return None

            qr_modules = len(matrix)
            # Scale up by module_size
            pixel_width = qr_modules * module_size
            pixel_height = qr_modules * module_size

            # TSPL BITMAP: width_bytes = ceil(pixel_width / 8)
            width_bytes = (pixel_width + 7) // 8

            # Build bitmap data row by row (scaled)
            bitmap_data = bytearray()
            for row in matrix:
                # Build one pixel row
                pixel_row = bytearray(width_bytes)
                for col_idx, module_on in enumerate(row):
                    if module_on:
                        for s in range(module_size):
                            bit_pos = col_idx * module_size + s
                            byte_idx = bit_pos // 8
                            bit_idx = 7 - (bit_pos % 8)
                            if byte_idx < width_bytes:
                                pixel_row[byte_idx] |= (1 << bit_idx)
                # Repeat row for module_size height
                for _ in range(module_size):
                    bitmap_data.extend(pixel_row)

            return {
                'width_bytes': width_bytes,
                'height': pixel_height,
                'data': bytes(bitmap_data)
            }
        except Exception as e:
            logger.error(f"Error generating QR bitmap: {e}")
            return None

    def _generate_registration_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for wholesale registration label.

        Label layout (1" x 3"):
        +---------------------------------------------------+
        |  [QR CODE]   SUNDIAL AUDIO                        |
        |  [QR CODE]   Register Your Cable                  |
        |  [QR CODE]   XKDF-7M2P            #SD000123      |
        |              sundial.audio/register    SC-20GL     |
        +---------------------------------------------------+

        Args:
            data: Dictionary with:
                - registration_code: str (e.g., "XKDF-7M2P")
                - registration_url: str (full URL with code)
                - serial_number: str
                - sku: str

        Returns:
            TSPL commands as bytes
        """
        reg_code = data.get('registration_code', '')
        reg_url = data.get('registration_url', '')
        serial_number = data.get('serial_number', '')
        sku = data.get('sku', '')

        # Start TSPL commands
        tspl_commands = []
        tspl_commands.append(f"SIZE {self.label_width_mm:.1f} mm, {self.label_height_mm:.1f} mm")
        tspl_commands.append("GAP 2 mm, 2 mm")
        tspl_commands.append("DIRECTION 1,0")
        tspl_commands.append("REFERENCE 0,0")
        tspl_commands.append("SET TEAR ON")
        tspl_commands.append("SET PEEL OFF")
        tspl_commands.append("CLS")
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        # QR code on left (~0.6" square = ~122 dots at 203 DPI)
        # Position QR at x=10, y=10
        qr_x = 10
        qr_y = 10

        # Generate QR bitmap for the registration URL
        qr_bitmap = self._generate_qr_bitmap(reg_url, module_size=3)

        # Text positions (right of QR code)
        x_text = 145  # Right of QR code area
        x_right = 450  # Right-aligned items

        # Y positions
        y_brand = 12
        y_subtitle = 45
        y_code = 80
        y_url = 130
        y_serial = 80
        y_sku = 130

        # Brand
        tspl_commands.append(f'TEXT {x_text},{y_brand},"3",0,1,1,"SUNDIAL AUDIO"')

        # Subtitle
        tspl_commands.append(f'TEXT {x_text},{y_subtitle},"2",0,1,1,"Register Your Cable"')

        # Registration code (large, prominent)
        tspl_commands.append(f'TEXT {x_text},{y_code},"3",0,1,1,"{reg_code}"')

        # Serial number on right
        if serial_number:
            tspl_commands.append(f'TEXT {x_right},{y_serial},"2",0,1,1,"#{serial_number}"')

        # URL at bottom left of text area
        tspl_commands.append(f'TEXT {x_text},{y_url},"1",0,1,1,"sundial.audio/register"')

        # SKU at bottom right
        if sku:
            tspl_commands.append(f'TEXT {x_right},{y_sku},"1",0,1,1,"{sku}"')

        # Decorative line under brand
        tspl_commands.append(f'BAR {x_text},{y_brand + 28},300,2')

        # QR code bitmap placeholder
        tspl_commands.append("__QR_CODE__")

        # Print
        tspl_commands.append("PRINT 1")
        tspl_commands.append("")

        # Build output as bytes
        output = b''
        for cmd in tspl_commands:
            if cmd == '__QR_CODE__':
                if qr_bitmap:
                    bitmap_cmd = f'BITMAP {qr_x},{qr_y},{qr_bitmap["width_bytes"]},{qr_bitmap["height"]},0,'.encode()
                    output += bitmap_cmd + qr_bitmap['data'] + b'\r\n'
            else:
                output += cmd.encode('utf-8') + b'\r\n'

        return output

    def _generate_wire_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for Sundial Wire product label.

        Label layout (1" x 3"):
        +---------------------------------------------------+
        |  [QR CODE]   SUNDIAL WIRE                         |
        |  [QR CODE]   ────────────────                     |
        |  [QR CODE]   Product Name Here That               |
        |              Wraps If Needed                       |
        |              SKU-123-ABC                           |
        +---------------------------------------------------+

        Args:
            data: Dictionary with:
                - product_title: str (product name from Shopify)
                - sku: str
                - product_url: str (full URL for QR code)

        Returns:
            TSPL commands as bytes
        """
        product_title = data.get('product_title', '')
        sku = data.get('sku', '')
        product_url = data.get('product_url', '')

        # Start TSPL commands
        tspl_commands = []
        tspl_commands.append(f"SIZE {self.label_width_mm:.1f} mm, {self.label_height_mm:.1f} mm")
        tspl_commands.append("GAP 2 mm, 2 mm")
        tspl_commands.append("DIRECTION 1,0")
        tspl_commands.append("REFERENCE 0,0")
        tspl_commands.append("SET TEAR ON")
        tspl_commands.append("SET PEEL OFF")
        tspl_commands.append("CLS")
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        # QR code on left (~0.6" square = ~122 dots at 203 DPI)
        qr_x = 10
        qr_y = 10

        # Generate QR bitmap for the product URL
        qr_bitmap = self._generate_qr_bitmap(product_url, module_size=3) if product_url else None

        # Text positions (right of QR code, with clearance for large QR codes)
        x_text = 170

        # Y positions
        y_brand = 12
        y_line = y_brand + 28  # Decorative line under brand
        y_title = 50
        y_title_line2 = 80  # Second line of title if wrapped
        y_sku = 130

        # Brand header
        tspl_commands.append(f'TEXT {x_text},{y_brand},"3",0,1,1,"SUNDIAL WIRE"')

        # Decorative line under brand
        tspl_commands.append(f'BAR {x_text},{y_line},300,2')

        # Product title (word-wrap if long)
        title_parts = self._split_text(product_title, max_length=28)
        tspl_commands.append(f'TEXT {x_text},{y_title},"2",0,1,1,"{title_parts[0]}"')
        if len(title_parts) > 1:
            tspl_commands.append(f'TEXT {x_text},{y_title_line2},"2",0,1,1,"{title_parts[1]}"')
            # SKU goes below second title line
            y_sku = y_title_line2 + 30
        else:
            # SKU goes below first title line
            y_sku = y_title + 30

        # SKU
        tspl_commands.append(f'TEXT {x_text},{y_sku},"2",0,1,1,"{sku}"')

        # QR code bitmap placeholder
        tspl_commands.append("__QR_CODE__")

        # Print
        tspl_commands.append("PRINT 1")
        tspl_commands.append("")

        # Build output as bytes
        output = b''
        for cmd in tspl_commands:
            if cmd == '__QR_CODE__':
                if qr_bitmap:
                    bitmap_cmd = f'BITMAP {qr_x},{qr_y},{qr_bitmap["width_bytes"]},{qr_bitmap["height"]},0,'.encode()
                    output += bitmap_cmd + qr_bitmap['data'] + b'\r\n'
            else:
                output += cmd.encode('utf-8') + b'\r\n'

        return output

    def _format_connector_type(self, connector_type: str) -> str:
        """Format connector type for display on label"""
        # Normalize en-dashes/em-dashes to ASCII hyphens (DB uses en-dashes)
        normalized = connector_type.replace('\u2013', '-').replace('\u2014', '-')

        # Map connector types to display text
        connector_map = {
            'TS-TS': 'Straight TS',
            'TRS-TRS': 'Straight TRS',
            'TS-TRS': 'TS to TRS',
            'XLR-XLR': 'XLR to XLR',
            'XLR-TRS': 'XLR to TRS',
            'RA-TS': 'Right Angle TS',
            'TS-RA': 'Right Angle TS',
            'Straight': 'Straight Connectors',
            'Right Angle': 'Right Angle',
        }
        return connector_map.get(normalized, normalized)

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

    def __init__(self, ip_address: str = "tsc", port: int = 9100):
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
            logger.debug("Mock TSPL commands would be generated for cable label")
        elif print_job.template == "registration_label":
            logger.debug("Mock TSPL commands would be generated for registration label")
        elif print_job.template == "wire_label":
            logger.debug("Mock TSPL commands would be generated for wire label")

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
