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


# The two label stocks in use. The TE210 has one media path, so running both
# means swapping the roll.
CABLE_ROLL_MM = (76.2, 25.4)   # 1" x 3"
BOX_STOCK_MM = (76.2, 50.8)    # 2" x 3"

# The stock each template is designed for. This is data rather than an
# `if template == "box_label"` branch because two things need it: batching a
# job set by stock, so a run costs one roll swap instead of one per label; and
# routing to a second printer by what it has loaded, once there is one.
LABEL_STOCK = {
    "cable_label":        CABLE_ROLL_MM,
    "registration_label": CABLE_ROLL_MM,
    "wire_label":         CABLE_ROLL_MM,
    "barcode_label":      CABLE_ROLL_MM,
    "bin_label":          CABLE_ROLL_MM,
    "shelf_label":        CABLE_ROLL_MM,
    "text_label":         CABLE_ROLL_MM,
    "prop65_label":       CABLE_ROLL_MM,
    "box_label":          BOX_STOCK_MM,
}


def stock_for_template(template: str) -> Optional[tuple]:
    """(width_mm, height_mm) the template is designed for, or None."""
    return LABEL_STOCK.get(template)


def _tspl_safe(text: Optional[str]) -> str:
    """Make a string safe to drop inside a TSPL TEXT command's quotes.

    Two hazards. TSPL delimits TEXT content with `"` and offers no escape for
    one, so a stray quote truncates the command and the rest of the line ends
    up interpreted as TSPL. And the TE210's built-in bitmap fonts render a
    single-byte codepage, so multi-byte UTF-8 prints as garbage — which the
    catalog YAML would hand us, since it writes connector displays with
    en-dashes ('TS–TS').

    So: fold the dashes and smart quotes to ASCII, drop anything still
    non-ASCII, then swap `"` for `'`.
    """
    if not text:
        return ''
    folded = (text.replace('\u2013', '-').replace('\u2014', '-')
                  .replace('\u2018', "'").replace('\u2019', "'")
                  .replace('\u201c', '"').replace('\u201d', '"')
                  # Prime / double prime: Shopify titles use these for feet
                  # and inches. Folding beats dropping them, which turned
                  # "20\u2032" into a bare "20".
                  .replace('\u2032', "'").replace('\u2033', '"'))
    ascii_only = ''.join(c for c in folded if 32 <= ord(c) < 127)
    return ascii_only.replace('"', "'")



def prop65_warning(form=None, chemical=None, endpoints=None):
    """The Prop 65 warning as (signal word, sentence).

    With a chemical named, the short form is the 2025 safe-harbor text
    (27 CCR 25603(b)), which names one and may use "CA WARNING". It is
    REQUIRED for products manufactured from 1 January 2028; until then the
    old unnamed form below remains safe harbor, with unlimited sell-through
    for stock made before that date.

    The words are the regulation's, not ours -- check them against
    25603(b) before changing anything here.
    """
    form = (form or "short").lower()
    chemical = (chemical or "").strip()
    endpoints = (endpoints or "both").lower()
    url = "www.P65Warnings.ca.gov."

    if form == "long":
        harm = {"cancer": "cause cancer",
                "reproductive": "cause birth defects or other reproductive harm",
                }.get(endpoints,
                      "cause cancer and birth defects or other reproductive harm")
        chem = chemical or "chemicals"
        is_are = "which is" if chemical else "which are"
        return "WARNING", (f"This product can expose you to {chem}, {is_are} "
                           f"known to the State of California to {harm}. For "
                           f"more information go to {url}")

    if chemical:
        kind = {"cancer": "a carcinogen",
                "reproductive": "a reproductive toxicant",
                }.get(endpoints, "a carcinogen and reproductive toxicant")
        return "CA WARNING", f"Can expose you to {chemical}, {kind}. See {url}"

    harm = {"cancer": "Cancer", "reproductive": "Reproductive Harm",
            }.get(endpoints, "Cancer and Reproductive Harm")
    return "WARNING", f"{harm} - {url}"


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

    # template name -> generator method. One table, used by both this class
    # and the mock, so a new template cannot be wired into one and not the
    # other. Its keys must match LABEL_STOCK exactly; a test holds that.
    TEMPLATES = {
        "cable_label":        "_generate_cable_label_tspl",
        "registration_label": "_generate_registration_label_tspl",
        "wire_label":         "_generate_wire_label_tspl",
        "barcode_label":      "_generate_barcode_label_tspl",
        "bin_label":          "_generate_bin_label_tspl",
        "shelf_label":        "_generate_shelf_label_tspl",
        "box_label":          "_generate_box_label_tspl",
        "text_label":         "_generate_text_label_tspl",
        "prop65_label":       "_generate_prop65_label_tspl",
    }

    # Inter-label gap, in mm. The printer's own SELFTEST reports the measured
    # gap as 0.08 in = 2.03 mm. Never 0: `GAP 0,0` means continuous media,
    # which leaves the printer no top-of-form to register against at all.
    GAP_MM = 2.0

    # Vertical registration per stock, MEASURED on this printer with
    # tools/printer/calibrate_media.py --measure:
    #   gap_offset_mm -- the n in `GAP m,n`
    #   shift         -- TSPL `SHIFT`, in dots (+ moves the image down)
    #
    # Both are sent with EVERY label (see _media_header), never left to the
    # printer: SHIFT persists in the printer's memory, so a value sent while
    # tuning one stock silently moves every label on the other. That is what
    # broke the 1" roll in October 2026 -- a shift saved during the 2" work
    # pushed 1" labels ~25 dots down and cut off the side label's SKU.
    #
    # The 1" figures are what the cable labels printed with for months, and
    # were re-confirmed 2026-10-08 (ruler ticks flush to the top edge, 200 on
    # the left ruler just clipped, of 203). An earlier change set the offset
    # to 0 on the theory that die-cut stock needs none; on this printer it
    # does, and the measurement is what counts.
    MEDIA_REGISTRATION = {
        CABLE_ROLL_MM: {"gap_offset_mm": 2.0, "shift": 0},
        BOX_STOCK_MM:  {"gap_offset_mm": 2.0, "shift": 0},
    }
    # The 2" figures were measured the same day: after GAPDETECT on that roll
    # the top ticks were whole, and an SC-20GL box label printed with the
    # UPC digits whole and room to spare beneath them. Same printer, same
    # sensor, same answer -- but measured, not assumed.

    @classmethod
    def _media_header(cls, width_mm: float, height_mm: float) -> list:
        """The setup every label starts with: size, gap, registration.

        One place, so the nine templates cannot drift apart, and explicit
        about everything the printer would otherwise remember from the last
        job (see MEDIA_REGISTRATION).
        """
        reg = cls.MEDIA_REGISTRATION.get(
            (round(width_mm, 1), round(height_mm, 1)),
            {"gap_offset_mm": 0.0, "shift": 0})
        return [
            f"SIZE {width_mm:.1f} mm, {height_mm:.1f} mm",
            f"GAP {cls.GAP_MM:.1f} mm, {reg['gap_offset_mm']:.1f} mm",
            "DIRECTION 1,0",
            "REFERENCE 0,0",
            # After SIZE: sent ahead of it, the printer discards the job.
            f"SHIFT {reg['shift']}",
            "SET TEAR ON",
            "SET PEEL OFF",
            "CLS",
        ]

    # Horizontal advance per character, in dots, MEASURED on this printer --
    # see tools/printer/calibrate_media.py --measure, which prints a vertical
    # line where each font is predicted to end so the reading is unambiguous.
    #
    # All five are read off a printed calibration label. Fonts "1" and "2"
    # advance 2 dots more than the TSPL manual documents (10 and 14, against
    # 8 and 12); "3", "4" and "5" match it exactly. There is no pattern: the
    # first theory was a uniform "cell width + 2" inferred from font "2"
    # alone, and it was wrong for three of the five. Measure, don't infer --
    # tools/printer/calibrate_media.py --measure prints a vertical line where
    # each font is predicted to end, so the reading is unambiguous.
    #
    # Any template placing text by character count must use these: box_label
    # was laid out with the manual's figures and put "SUNDIAL" 6 dots into
    # the logo and a long SKU 18 dots off the edge.
    FONT_ADVANCE = {"1": 10, "2": 14, "3": 16, "4": 24, "5": 32}

    @staticmethod
    def _print_quantity(data: Dict[str, Any]) -> int:
        """Copies to print, from `data['quantity']`, floored at 1.

        TSPL `PRINT m,n` takes m sets of n copies, so the printer runs the
        repeat itself. Every template used to hardcode `PRINT 1` while
        print_labels logged that it had printed `print_job.quantity` -- so a
        job for 12 labels produced one, and said it produced 12.
        """
        try:
            return max(1, int(data.get('quantity', 1) or 1))
        except (TypeError, ValueError):
            return 1

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

    def calibrate_media(self, stock) -> bool:
        """Point the media sensor at a newly loaded roll.

        Every template sends SIZE and GAP, but those only say how big a label
        is -- not where the next one starts. After a roll swap the printer
        is still registered to the old stock's gaps, so the image lands off
        the label: on the 1" side label the SKU, 11 dots off the bottom, is
        the first thing lost. `GAPDETECT` feeds a few labels while it
        re-measures; that is expected, not a fault.

        tools/printer/calibrate_media.py does the same from the command line,
        plus an alignment label.

        Args:
            stock: (width_mm, height_mm), e.g. CABLE_ROLL_MM or BOX_STOCK_MM
        """
        if not self.connected and not self.initialize():
            return False
        width_mm, height_mm = stock
        tspl = "\r\n".join(
            self._media_header(width_mm, height_mm) + ["GAPDETECT", ""])
        if not self._send_tspl_commands(tspl):
            return False
        self.loaded_stock = (width_mm, height_mm)
        logger.info("Calibrated media for %.1f x %.1f mm", width_mm, height_mm)
        return True

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

        generator = self.TEMPLATES.get(print_job.template)
        if generator is None:
            logger.error(f"Unknown template: {print_job.template}")
            return False

        try:
            # Copies are the printer's job: TSPL `PRINT m,n` runs them from a
            # single command, so one connection prints the lot. The generators
            # read the count from data, which is also how a caller can set it
            # without going through PrintJob.
            data = dict(print_job.data or {})
            data.setdefault('quantity', print_job.quantity)
            quantity = self._print_quantity(data)

            tspl = getattr(self, generator)(data)
            success = self._send_tspl_commands(tspl)

            if success:
                logger.info(f"Successfully printed {quantity} label(s)")

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
        # color_pattern / connector_type are catalog-only after Phase 3.4 (None for
        # MISC/LTD via the resolver). Default to 'Unknown' if absent OR None so
        # downstream string formatting stays safe.
        color_pattern = data.get('color_pattern') or 'Unknown'
        connector_type = data.get('connector_type') or 'Unknown'
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

        # Format connector type for display, appending a non-standard finish
        # (custom/LTD builds, e.g. Black/Gold) so the physical label reflects it.
        connector_display = self._format_connector_type(connector_type)
        connector_finish = data.get('connector_finish')
        if connector_finish:
            connector_display = f"{connector_display} ({connector_finish})"

        # MISC and LTD variants get distinct line-3 branding instead of color/pattern
        from greenlight.db import sku_kind
        kind = sku_kind(sku)
        is_misc = kind == 'misc'
        is_ltd = kind == 'ltd'

        # Start TSPL commands
        tspl_commands = []

        # Set label size (width, height in mm)
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))

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
        # Label is 3" wide = ~609 dots; printable area cuts off near x≈556.
        x_left = 20
        # Serial number and SKU sit on the top-right. Shifted further left
        # than the QC column so long LTD SKUs like 'TV-25-LTD-GREENRIVER2026'
        # don't run off the edge. AUDIO logo on line 1 ends around x≈270.
        x_id = 340
        x_qc = 420   # QC results column on right side

        # Line 1: SUNDIAL [wire] AUDIO and serial number + SKU
        tspl_commands.append(f'TEXT {x_left},{y_brand},"3",0,1,1,"SUNDIAL"')
        # Wire logo between SUNDIAL and AUDIO - will be inserted as binary
        wire_logo_position = len(tspl_commands)  # Mark position for bitmap
        tspl_commands.append('__WIRE_LOGO__')  # Placeholder
        tspl_commands.append(f'TEXT {x_left + 190},{y_brand},"3",0,1,1,"AUDIO"')
        if serial_number:
            tspl_commands.append(f'TEXT {x_id},{y_serial},"2",0,1,1,"#{serial_number}"')
        # SKU under serial number
        tspl_commands.append(f'TEXT {x_id},{y_sku_right},"1",0,1,1,"{sku}"')

        # Add small decorative line under brand
        tspl_commands.append(f'BAR {x_left},{y_brand + 28},300,2')

        # Line 2: Series name
        tspl_commands.append(f'TEXT {x_left},{y_series},"2",0,1,1,"{series}"')

        # QC results in a tight column on the right (if tested)
        if has_test_results:
            cont_status = "PASS" if continuity_pass else "X"
            tspl_commands.append(f'TEXT {x_qc},{y_qc_con},"1",0,1,1,"CON: {cont_status}"')

        # Line 3: Length and Color/Pattern (with branding for MISC and LTD variants)
        if is_misc:
            length_text = f"{length}' Special Baby"
        elif is_ltd:
            length_text = f"{length}' Limited Edition"
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
        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
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
        |              REGISTER YOUR CABLE                   |
        |  [QR CODE]   XKDF-7M2P                            |
        |  [QR CODE]   sundialaudio.com/register             |
        |              Take full advantage of our buy-it-    |
        |              for-life warranty by registering...   |
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

        # Start TSPL commands
        tspl_commands = []
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        # Label is 609 x 203 dots (3" x 1" at 203 DPI)
        # QR bitmap is ~87x87 dots at module_size=3
        qr_size = 87
        qr_x = 10
        qr_y = (self.label_height_dots - qr_size) // 2  # Vertically centered

        # Generate QR bitmap for the registration URL
        qr_bitmap = self._generate_qr_bitmap(reg_url, module_size=3)

        # Text positions (right of QR code, which extends to ~x=97)
        x_text = 160

        # Y positions — distribute across the 203-dot height
        y_title = 8
        y_code = 55
        y_url = 95
        y_warranty = 140

        # Title
        tspl_commands.append(f'TEXT {x_text},{y_title},"3",0,1,1,"REGISTER YOUR CABLE"')

        # Decorative line under title
        tspl_commands.append(f'BAR {x_text},{y_title + 28},370,2')

        # Registration code (large, prominent)
        tspl_commands.append(f'TEXT {x_text},{y_code},"3",0,1,1,"{reg_code}"')

        # URL
        tspl_commands.append(f'TEXT {x_text},{y_url},"2",0,1,1,"sundialaudio.com/register"')

        # Warranty message
        tspl_commands.append(f'TEXT {x_text},{y_warranty},"1",0,1,1,"Take advantage of our buy-it-for-life"')
        tspl_commands.append(f'TEXT {x_text},{y_warranty + 18},"1",0,1,1,"warranty by registering your cable today!"')

        # QR code bitmap placeholder
        tspl_commands.append("__QR_CODE__")

        # Print
        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
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
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))
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
        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
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

    def _generate_bin_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for a finished-goods BIN label.

        Staff-facing (NOT customer-facing): no branding, no website QR — that
        is the sample-card `wire_label` template's job. A bin label is just the
        product name plus a large Code 128 barcode of the SKU. Shopify POS scans
        that barcode against the variant Barcode field on the "Prepare for
        pickup" screen to fulfill the order, so one label = one variant.

        Label layout (1" x 3"):
        +---------------------------------------------------+
        |  Product Name Here That Wraps If Needed           |
        |                                                   |
        |      ||||| |||| || ||||| ||| ||||  (Code 128)     |
        |                   SC-20GL                          |
        +---------------------------------------------------+

        Args:
            data: Dictionary with:
                - sku: str (required — encoded in the Code 128 barcode)
                - product_title / title: str (optional product name, top line)
                - subtitle: str (optional second line, e.g. length/connector)

        Returns:
            TSPL commands as bytes
        """
        sku = (data.get('sku') or '').strip()
        title = data.get('product_title') or data.get('title') or ''
        subtitle = data.get('subtitle') or ''

        tspl_commands = []
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        x_left = 20

        # Product name across the top (word-wrap up to 2 lines)
        y = 14
        if title:
            for part in self._split_text(title, max_length=32)[:2]:
                tspl_commands.append(f'TEXT {x_left},{y},"3",0,1,1,"{part}"')
                y += 30
        if subtitle:
            tspl_commands.append(f'TEXT {x_left},{y},"2",0,1,1,"{subtitle}"')
            y += 26

        # Large Code 128 barcode of the SKU, with the SKU printed beneath it
        # (human-readable flag = 1). Approximate the rendered width to center it:
        # Code 128 ≈ 11 modules per char + 35 for start/check/stop, times the
        # narrow-element width in dots, plus a quiet-zone allowance.
        narrow = 2
        wide = 4
        est_width = (len(sku) * 11 + 35) * narrow + 40
        barcode_x = max(x_left, (self.label_width_dots - est_width) // 2)
        barcode_y = max(y + 6, 60)
        # Leave ~26 dots under the bars for the human-readable text
        barcode_height = max(50, min(90, self.label_height_dots - barcode_y - 26))
        tspl_commands.append(
            f'BARCODE {barcode_x},{barcode_y},"128",{barcode_height},1,0,{narrow},{wide},"{sku}"'
        )

        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
        tspl_commands.append("")

        return "\r\n".join(tspl_commands).encode('utf-8')

    # UPC-A geometry. A UPC-A symbol is 95 modules of bars plus a 9-module
    # quiet zone each side. At 203 DPI the module width ("narrow") can only be
    # a whole number of dots, so magnification comes in jumps:
    #   narrow=2 -> X=0.250mm, 75.8% — legal ONLY under the GS1 carve-out for
    #               on-demand thermal printing (75% floor), with no margin.
    #   narrow=3 -> X=0.375mm, 113.7% — comfortably mid-spec, but the
    #               proportional bar height (1.02") will not fit 1" stock.
    # Hence narrow=3 on taller stock as the default; see BOX_LABEL_*_MM below.
    UPCA_MODULES = 95
    UPCA_NOMINAL_X_IN = 0.013      # X-dimension at 100% magnification
    UPCA_NOMINAL_BARS_IN = 0.9     # bar height at 100%, excluding the digits

    # Retail box labels use their own, taller stock than the 1"x3" cable roll.
    BOX_LABEL_WIDTH_MM, BOX_LABEL_HEIGHT_MM = BOX_STOCK_MM

    # Dots at the bottom of the stock to keep clear under the UPC's digits,
    # which GS1 requires legible. History, because each number was a
    # reaction to the one before: 14 cut the digits off; 55 was the fix --
    # but the real cause was registration (labels printing ~25 dots low; see
    # MEDIA_REGISTRATION), so 55 overcorrected once that was fixed. Measured
    # 2026-10-08 with correct registration, the 2" roll prints reliably to
    # ~y=390 of 406, so 30 puts the digits' bottom at 376 with 15 dots of
    # slack, and centres the symbol between the text and the edge.
    BOX_LABEL_BOTTOM_MARGIN = 30

    def _generate_box_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for a retail box label with a UPC-A barcode.

        Customer-facing, for cables boxed for sale through retail stores. The
        UPC is what a store's POS scans, so the symbol is sized to spec and
        anchored to the bottom of the label at a fixed position — a barcode
        that moves around between SKUs is a barcode that gets mis-scanned.
        Text flows from the top and is allowed to wrap into the space left.

        Label layout (2" x 3" default):
        +---------------------------------------------------+
        |  SUNDIAL AUDIO                         SC-20GL    |
        |  -----------------------------------------------  |
        |  Studio Classic                                   |
        |  20 ft - Goldline - TS-TS                         |
        |                                                   |
        |         ||| || |||| | || ||| || |||| |            |
        |         0 36000 29145 2                           |
        +---------------------------------------------------+

        Args:
            data: Dictionary with:
                - upc: str (required) — a valid GTIN-12; the printer is handed
                  the first 11 digits and derives the check digit itself
                - product_title / title: str (optional) — top text line
                - subtitle: str (optional) — spec line (length/pattern/conn)
                - sku: str (optional) — printed small at top right
                - label_width_mm / label_height_mm: float (optional) — stock
                  size override, defaulting to the box-label stock constants
                  rather than this printer's cable-roll size

        Returns:
            TSPL commands as bytes

        Raises:
            ValueError: if `upc` is missing or not a valid GTIN-12. A box
                label with a wrong barcode is worse than no label, so this
                refuses rather than printing something unscannable.
        """
        from greenlight.gtin import upca_payload

        upc = (data.get('upc') or '').strip()
        if not upc:
            raise ValueError("box_label requires a 'upc' (GTIN-12)")
        # Raises ValueError with the specific reason on a bad check digit.
        payload = upca_payload(upc)

        title = data.get('product_title') or data.get('title') or ''
        subtitle = data.get('subtitle') or ''
        sku = (data.get('sku') or '').strip()

        # Box stock is taller than the cable roll this printer is configured
        # for, so these templates carry their own size rather than inheriting
        # self.label_*_mm.
        width_mm = float(data.get('label_width_mm') or self.BOX_LABEL_WIDTH_MM)
        height_mm = float(data.get('label_height_mm') or self.BOX_LABEL_HEIGHT_MM)
        width_dots = int(width_mm * self.dpi / 25.4)
        height_dots = int(height_mm * self.dpi / 25.4)

        # Pick the largest in-spec module width the stock can actually hold,
        # falling back to the thermal-only 75% floor on short stock so a 1"
        # roll still produces something rather than nothing.
        narrow = 3
        bars_h = int(self.UPCA_NOMINAL_BARS_IN * (narrow / self.dpi)
                     / self.UPCA_NOMINAL_X_IN * self.dpi)
        hri_h = 28          # room under the bars for the human-readable digits
        if bars_h + hri_h + 60 > height_dots:
            narrow = 2
            bars_h = int(self.UPCA_NOMINAL_BARS_IN * (narrow / self.dpi)
                         / self.UPCA_NOMINAL_X_IN * self.dpi)
            logger.warning(
                "Box label stock is %.1fmm tall — falling back to narrow=2 "
                "(75.8%% magnification, the GS1 thermal-print floor). 2in "
                "stock is strongly preferred for retail UPCs.", height_mm
            )

        tspl_commands = []
        tspl_commands.extend(self._media_header(width_mm, height_mm))
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        x_left = 20

        # The barcode is the one element that must be geometrically correct,
        # so it is placed first, a fixed distance up from the bottom edge, and
        # the text gets whatever is left above it. HEADER_H is the brand line
        # plus its divider rule; if that won't fit above the bars, the label
        # degrades to barcode-only rather than printing text over the bars.
        HEADER_H = 46
        barcode_y = height_dots - bars_h - hri_h - self.BOX_LABEL_BOTTOM_MARGIN
        y = 10
        usable = width_dots - 2 * x_left
        logo_w = self.wire_logo_data['width'] if self.wire_logo_data else 0
        logo_gap = 12

        if barcode_y >= y + HEADER_H:
            # Brand block: "SUNDIAL" [logo] "AUDIO". Each piece is placed
            # after the measured end of the one before it -- hardcoded
            # offsets had "SUNDIAL" running 6 dots into the logo, because
            # they were derived from the manual's font widths rather than
            # the printer's actual advance.
            brand_adv = self.FONT_ADVANCE["3"]
            tspl_commands.append(f'TEXT {x_left},{y},"3",0,1,1,"SUNDIAL"')
            logo_x = x_left + len("SUNDIAL") * brand_adv + logo_gap
            tspl_commands.append(f'__WIRE_LOGO__{logo_x}')
            audio_x = logo_x + logo_w + logo_gap
            tspl_commands.append(f'TEXT {audio_x},{y},"3",0,1,1,"AUDIO"')
            brand_end = audio_x + len("AUDIO") * brand_adv

            if sku:
                # Right-aligned in what the brand block leaves. Drops to
                # font "1" rather than running off the edge or over "AUDIO",
                # which a long LTD SKU ('SC-12-LTD-PHISH26-R') otherwise did.
                for sku_font in ("2", "1"):
                    adv = self.FONT_ADVANCE[sku_font]
                    sku_x = width_dots - x_left - len(sku) * adv
                    if sku_x >= brand_end + logo_gap:
                        break
                sku_x = max(brand_end + logo_gap, sku_x)
                fits = max(1, (width_dots - x_left - sku_x) // adv)
                tspl_commands.append(
                    f'TEXT {sku_x},{y + 6},"{sku_font}",0,1,1,"{sku[:fits]}"')
            y += 32
            tspl_commands.append(f'BAR {x_left},{y},{usable},2')
            y += 14

            # Both of these come from Shopify, so they can be any length and
            # can carry en-dashes or smart quotes: clip to the row, and run
            # them through _tspl_safe rather than only swapping quotes.
            if title:
                title_chars = max(1, usable // self.FONT_ADVANCE["3"])
                for part in self._split_text(title, max_length=title_chars)[:2]:
                    if barcode_y - y < 28:
                        break
                    safe = _tspl_safe(part)[:title_chars]
                    tspl_commands.append(f'TEXT {x_left},{y},"3",0,1,1,"{safe}"')
                    y += 28
            if subtitle and barcode_y - y >= 26:
                sub_chars = max(1, usable // self.FONT_ADVANCE["2"])
                safe = _tspl_safe(subtitle)[:sub_chars]
                tspl_commands.append(f'TEXT {x_left},{y},"2",0,1,1,"{safe}"')
        else:
            # Too short for branding — center the symbol and print nothing
            # else. Keeps a 1" roll usable as a plain UPC sticker.
            barcode_y = max(4, (height_dots - bars_h - hri_h) // 2)
            logger.warning(
                "Box label stock is only %d dots tall — printing barcode-only "
                "(no brand/title). Use 2in stock for a full retail label.",
                height_dots
            )

        # Center the bars on the label. TSPL does not add quiet zones itself,
        # but centering a 95-module symbol on 3" stock leaves far more than
        # the 9 modules required on each side.
        bars_w = self.UPCA_MODULES * narrow
        barcode_x = max(x_left, (width_dots - bars_w) // 2)
        # BARCODE x,y,"code type",height,human readable,rotation,narrow,wide,"content"
        tspl_commands.append(
            f'BARCODE {barcode_x},{barcode_y},"UPCA",{bars_h},1,0,{narrow},'
            f'{narrow},"{payload}"'
        )

        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
        tspl_commands.append("")

        # Build output as bytes, handling the inline logo bitmap
        output = b''
        for cmd in tspl_commands:
            if cmd.startswith('__WIRE_LOGO__'):
                bitmap_cmd = self._get_bitmap_command(
                    int(cmd[len('__WIRE_LOGO__'):]), 12)
                if bitmap_cmd:
                    output += bitmap_cmd + b'\r\n'
            else:
                output += cmd.encode('utf-8') + b'\r\n'

        return output

    # Shelf-label geometry, in dots at 203 DPI on the 1" x 3" cable roll
    # (609 x 203 dots). Positions are FIXED, not flowed: these labels sit side
    # by side on a retail shelf, so a line has to land in the same spot on
    # every box or a row of them reads as ragged. Fonts are the TE210's
    # built-in bitmaps -- "1" 8x12, "2" 12x20, "3" 16x24, "4" 24x32, "5" 32x48.
    SHELF_X_LEFT = 16
    # Extra right margin for the SKU, on top of the left gutter. It sits alone
    # in the corner, where a flush margin reads as a crop rather than as a
    # choice -- but 40 dots pulled it too far in from the edge, so: 12, for a
    # 28-dot margin against the 16-dot gutter.
    SHELF_X_SKU_PAD = 12
    # Eight rows of ink in 203 dots leaves about 4 between each, which the
    # bitmap fonts' own leading makes read as a gap. Everything is spoken for:
    # growing any row means shrinking another.
    # Six rows in 203 dots, with roughly even gaps -- 8 to 16 dots, which the
    # bitmap fonts' own leading widens a little further. An eight-row version
    # of this label left 4 dots between rows and read as a wall of text.
    # The pattern row deliberately does NOT sit tight against the spec row:
    # grouping them that way made the pattern look like a label on the length
    # rather than its own line.
    SHELF_Y_BRAND = 10          # font "3"
    SHELF_Y_RULE = 42
    SHELF_Y_PATTERN = 54        # font "3"
    SHELF_Y_SPEC = 92           # font "4" -- the headline of the label
    SHELF_Y_CONNECTOR = 140     # font "2"
    SHELF_Y_SKU = 172           # font "2", bottom-right, on its own row



    def _generate_shelf_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for a retail SHELF label (box side).

        Customer-facing, and the counterpart to `box_label`: a boxed cable
        carries the pattern sticker on the front and the 2"x3" UPC label on
        the back, but neither is visible once boxes are racked spine-out. This
        is what a browsing customer actually reads.

        Label layout (1" x 3"):
        +---------------------------------------------------------------+
        |  Sundial Audio Studio Series                                  |
        |  -----------------------------------------------------------  |
        |                                                               |
        |  Goldline                                                     |
        |  20' Instrument Cable                                         |
        |                                                               |
        |  TS-TS - Canare GS-6                                          |
        |                                             SC-20GL           |
        +---------------------------------------------------------------+

        There is deliberately NO braid description ("Black rayon braid with
        gold tracer"). The pattern row says the same thing in one word, and at
        up to three rows it was the single biggest thing on the label -- the
        space buys the gaps that stop the other six rows reading as a wall.
        `describe_variant()` still returns that copy as `detail` for callers
        that have room for it; this template just doesn't print it.

        The connector row is the product-facing designation, not the
        engineering shorthand: a right-angle cable is "TS-TS Right Angle",
        since both of its ends really are TS with one of them angled. Nothing
        states what can't be otherwise, so no row says a mic cable is XLR male
        to female.

        The core cable rides on that row rather than leading the description,
        because the description prints at font "2" and the two together run to
        110 characters against the 96 its two rows hold.

        Deliberately NO barcode: the UPC on the back is what a POS scans, and
        a second symbol here would eat the area that makes the label readable.
        The SKU is printed small in the corner so staff can restock a shelf
        without turning boxes over.

        Prints on this printer's own 1" x 3" cable roll (unlike `box_label`,
        which carries its own taller stock size).

        Args:
            data: Dictionary with (all optional -- any element missing is
                simply left off, so a partial label still prints):
                - brand_line: str, "Sundial Audio Studio Series" (font "3")
                - pattern: str, "Goldline" (font "3"). Falls back to
                  `headline` so a caller carrying series+pattern in one
                  string still gets the row.
                - spec_line: str, "20' Instrument Cable" (font "4", 24 chars
                  max -- the largest row on the label)
                - connector_line: str, "TS-TS - Canare GS-6" (font "2").
                  Falls back to `connector_label` alone.
                - sku: str, printed small at bottom right

                `cable_config.describe_variant(sku)` returns exactly these
                keys, so the usual call is
                `PrintJob("shelf_label", describe_variant(sku))`.

        Returns:
            TSPL commands as bytes
        """
        brand = _tspl_safe(data.get('brand_line'))
        # `headline` carries series+pattern in one string for callers that
        # don't have the pattern split out.
        pattern = (_tspl_safe(data.get('pattern'))
                   or _tspl_safe(data.get('headline')))
        spec = _tspl_safe(data.get('spec_line'))
        connector = (_tspl_safe(data.get('connector_line'))
                     or _tspl_safe(data.get('connector_label')))
        sku = _tspl_safe(data.get('sku')).strip()

        width_dots = self.label_width_dots
        x_left = self.SHELF_X_LEFT
        x_right = width_dots - x_left
        usable = x_right - x_left

        tspl_commands = []
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        # Every row is clipped to its own font's column width rather than
        # wrapped: the vertical budget is spoken for, so a row that outgrew
        # itself would have to push another off the label. The sweep in
        # tests/test_shelf_label.py fails on any catalog string that doesn't
        # fit, which is where a too-long name should be caught.
        def row(text, y, font):
            if not text:
                return
            advance = self.FONT_ADVANCE[font]
            tspl_commands.append(
                f'TEXT {x_left},{y},"{font}",0,1,1,'
                f'"{text[:max(1, usable // advance)]}"')

        row(brand, self.SHELF_Y_BRAND, "3")
        tspl_commands.append(f'BAR {x_left},{self.SHELF_Y_RULE},{usable},2')
        row(pattern, self.SHELF_Y_PATTERN, "3")
        row(spec, self.SHELF_Y_SPEC, "4")
        row(connector, self.SHELF_Y_CONNECTOR, "2")

        # Bottom-right, on a row of its own. Sharing the connector's row
        # would work for most variants but leaves the longest connector line
        # ("TS-TS Right Angle - Canare GS-6", 31 characters) ending 5 dots
        # short of the SKU -- and a third of the catalog is right-angle.
        # Font "2" unless the SKU is long enough to need "1".
        if sku:
            advance = self.FONT_ADVANCE["2"]
            sku_font = "2" if len(sku) * advance <= 160 else "1"
            sku_x = max(x_left, x_right - self.SHELF_X_SKU_PAD
                        - len(sku) * self.FONT_ADVANCE[sku_font])
            tspl_commands.append(
                f'TEXT {sku_x},{self.SHELF_Y_SKU},"{sku_font}",0,1,1,"{sku}"')

        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
        tspl_commands.append("")

        return "\r\n".join(tspl_commands).encode('utf-8')

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

    def _generate_barcode_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for a serial number barcode label.

        Label layout (1" x 3"):
        +---------------------------------------------------+
        |  SUNDIAL AUDIO                         SC-20GL    |
        |  ─────────────                                    |
        |  |||||||||||||||||||||||||||||||||||||||||||||||   |
        |  |||||||||||||||||||||||||||||||||||||||||||||||   |
        |              SD000123                              |
        +---------------------------------------------------+

        Args:
            data: Dictionary with:
                - serial_number: str (e.g., "SD000123")
                - sku: str (optional, e.g., "SC-20GL")

        Returns:
            TSPL commands as bytes
        """
        # `or ''` covers both missing keys and explicit None — resolver returns
        # None for color_pattern / connector_type on MISC/LTD variants.
        serial_number = data.get('serial_number') or ''
        sku = data.get('sku') or ''
        series = data.get('series') or ''
        length = data.get('length') or ''
        color_pattern = data.get('color_pattern') or ''
        connector_type = data.get('connector_type') or ''

        # Format length (database returns float)
        if isinstance(length, (int, float)):
            length = str(int(length)) if length == int(length) else str(length)

        # Format connector type
        connector_display = self._format_connector_type(connector_type) if connector_type else ''

        tspl_commands = []
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        x_left = 20
        x_right = 370

        # Brand header
        y_brand = 8
        tspl_commands.append(f'TEXT {x_left},{y_brand},"3",0,1,1,"SUNDIAL"')
        # Wire logo between SUNDIAL and AUDIO
        tspl_commands.append('__WIRE_LOGO__')
        tspl_commands.append(f'TEXT {x_left + 190},{y_brand},"3",0,1,1,"AUDIO"')

        # Decorative line
        tspl_commands.append(f'BAR {x_left},{y_brand + 28},560,2')

        # Code 128 barcode on left, human-readable text below
        # BARCODE x,y,"code type",height,human readable,rotation,narrow,wide,"content"
        barcode_x = 20
        barcode_y = 50
        barcode_height = 90
        tspl_commands.append(
            f'BARCODE {barcode_x},{barcode_y},"128",{barcode_height},1,0,2,4,"{serial_number}"'
        )

        # Cable details stacked on right side
        y_detail = 50
        if sku:
            tspl_commands.append(f'TEXT {x_right},{y_detail},"2",0,1,1,"{sku}"')
            y_detail += 25
        if series:
            tspl_commands.append(f'TEXT {x_right},{y_detail},"2",0,1,1,"{series}"')
            y_detail += 25
        if length and color_pattern:
            tspl_commands.append(f'TEXT {x_right},{y_detail},"2",0,1,1,"{length}\' {color_pattern}"')
            y_detail += 25
        if connector_display:
            tspl_commands.append(f'TEXT {x_right},{y_detail},"2",0,1,1,"{connector_display}"')

        # Print
        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
        tspl_commands.append("")

        # Build output as bytes, handling inline bitmap
        output = b''
        for cmd in tspl_commands:
            if cmd == '__WIRE_LOGO__':
                bitmap_cmd = self._get_bitmap_command(x_left + 120, y_brand + 2)
                if bitmap_cmd:
                    output += bitmap_cmd + b'\r\n'
            else:
                output += cmd.encode('utf-8') + b'\r\n'

        return output

    def _generate_text_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL commands for a simple text label.

        Prints one or more lines of arbitrary text, centered on the label.
        Useful for quick one-off labels (MAC addresses, asset tags, notes, etc).

        Args:
            data: Dictionary with:
                - lines: list[str] — text lines to print
                - title: str (optional) — bold header line
                - scale: int (optional) — font size multiplier (default 1)

        Returns:
            TSPL commands as bytes
        """
        lines = data.get('lines', [])
        title = data.get('title', '')
        # Font size multiplier applied to both width and height. Line spacing
        # scales with it so larger text doesn't overlap.
        scale = max(1, int(data.get('scale', 1) or 1))

        tspl_commands = []
        tspl_commands.extend(self._media_header(self.label_width_mm, self.label_height_mm))
        tspl_commands.append("DENSITY 10")
        tspl_commands.append("SPEED 3")

        x = 20
        y = 15

        if title:
            # Bold title using font "4" (larger)
            tspl_commands.append(f'TEXT {x},{y},"4",0,{scale},{scale},"{title}"')
            y += 35 * scale
            # Decorative line under title
            tspl_commands.append(f'BAR {x},{y},560,2')
            y += 15

        # Print each text line using font "3" (medium)
        for line in lines:
            # Escape quotes in text
            safe_line = line.replace('"', "'")
            tspl_commands.append(f'TEXT {x},{y},"3",0,{scale},{scale},"{safe_line}"')
            y += 30 * scale

        tspl_commands.append(f"PRINT {self._print_quantity(data)},1")
        tspl_commands.append("")

        return "\r\n".join(tspl_commands).encode('utf-8')

    def _generate_warning_triangle_bitmap(self, height: int = 88,
                                          border: int = 9) -> Dict[str, Any]:
        """Procedurally draw the Prop 65 warning symbol as a TSPL bitmap.

        The TE210 only renders built-in bitmap fonts, so the exclamation-point
        triangle can't be a glyph — we rasterize it here. Returns a dict shaped
        like _generate_qr_bitmap output (width_bytes, height, data) with the
        same convention: an "ink" pixel is bit=1, sent with BITMAP mode 0.

        Args:
            height: triangle height in dots
            border: stroke thickness of the triangle outline in dots
        """
        import math

        H = height
        m = 4  # margin so the stroke isn't clipped at the edges
        # Equilateral triangle: base width = 2 * height / sqrt(3).
        base = 2.0 * (H - 2 * m) / math.sqrt(3)
        W = int(math.ceil(base)) + 2 * m
        cx = W / 2.0

        # Vertices: apex top-center, base corners bottom-left / bottom-right.
        ax, ay = cx, float(m)
        bx, by = float(m), float(H - m)
        dx, dy = float(W - m), float(H - m)
        gx, gy = (ax + bx + dx) / 3.0, (ay + by + dy) / 3.0  # centroid

        def inside(px, py, va, vb, vc):
            """True if point is inside triangle va,vb,vc (edge sign test)."""
            def sign(p1, p2, p3):
                return ((p1[0] - p3[0]) * (p2[1] - p3[1]) -
                        (p2[0] - p3[0]) * (p1[1] - p3[1]))
            p = (px, py)
            d1, d2, d3 = sign(p, va, vb), sign(p, vb, vc), sign(p, vc, va)
            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
            return not (has_neg and has_pos)

        # Inner triangle = outer scaled toward the centroid, leaving a border of
        # ~`border` dots. Scale so the inradius shrinks by `border`.
        # inradius r = area / semiperimeter.
        area = abs((bx - ax) * (dy - ay) - (dx - ax) * (by - ay)) / 2.0
        peri = (math.dist((ax, ay), (bx, by)) +
                math.dist((bx, by), (dx, dy)) +
                math.dist((dx, dy), (ax, ay)))
        r = area / (peri / 2.0)
        s = max(0.0, 1.0 - border / r)

        def shrink(vx, vy):
            return (gx + s * (vx - gx), gy + s * (vy - gy))

        ia, ib, ic = shrink(ax, ay), shrink(bx, by), shrink(dx, dy)

        # Exclamation mark geometry (drawn black inside the white interior).
        bar_half = max(3, border // 2)
        bar_top = int(H * 0.34)
        bar_bot = int(H * 0.62)
        dot_cy = int(H * 0.75)
        dot_r = bar_half + 1

        width_bytes = (W + 7) // 8
        data = bytearray()
        for y in range(H):
            row = bytearray(width_bytes)
            for x in range(W):
                in_outer = inside(x + 0.5, y + 0.5, (ax, ay), (bx, by), (dx, dy))
                in_inner = inside(x + 0.5, y + 0.5, ia, ib, ic)
                on_ring = in_outer and not in_inner
                in_bar = (bar_top <= y <= bar_bot) and (abs(x - cx) <= bar_half)
                in_dot = ((x - cx) ** 2 + (y - dot_cy) ** 2) <= dot_r ** 2
                if on_ring or in_bar or in_dot:
                    row[x // 8] |= (1 << (7 - (x % 8)))
            data.extend(row)

        return {'width_bytes': width_bytes, 'height': H, 'width': W,
                'data': bytes(data)}

    def _generate_prop65_label_tspl(self, data: Dict[str, Any]) -> bytes:
        """Generate TSPL for a California Proposition 65 warning label.

        One calm sentence beside a modest warning triangle, the way the
        warning reads on most retail goods:

            /!\\  CA WARNING: Can expose you to lead, a
                 carcinogen and reproductive toxicant.
                 See www.P65Warnings.ca.gov.

        The previous layout put "WARNING" at double size with "Cancer and
        Reproductive Harm" as a headline beneath it, which read as an alarm
        rather than a disclosure. Nothing in the regulation asks for that:
        the signal word must be bold capitals and the text at least 6 pt, and
        a dedicated label has no other consumer text it must out-size. Font
        "3" (~8.5 pt) where it fits, "2" (~7.1 pt) where it doesn't -- never
        "1", which is ~4.3 pt. Bold is a double strike; the TE210's fonts
        have no bold weight.

        Wording is `prop65_warning()`'s -- see it for what each form says.

        Args:
            data: Dictionary with:
                - chemical: chemical name. Named -> the 2025 short form
                  (required on products made from 2028); omitted -> the old
                  "Cancer and Reproductive Harm" short form.
                - endpoints: "both" (default), "cancer", or "reproductive"
                - form: "short" (default) or "long"
                - quantity: number of copies (default 1)
        """
        signal, sentence = prop65_warning(
            form=data.get('form'), chemical=data.get('chemical'),
            endpoints=data.get('endpoints'))
        quantity = self._print_quantity(data)

        cmds = []
        cmds.extend(self._media_header(self.label_width_mm, self.label_height_mm))
        cmds.append("DENSITY 10")
        cmds.append("SPEED 3")

        height = self.label_height_dots
        tri = self._generate_warning_triangle_bitmap(height=64, border=6)
        margin = 16
        text_x = margin + tri['width'] + 16
        usable = self.label_width_dots - margin - text_x

        prefix = signal + ":"
        for font, row_h in (("3", 32), ("2", 26)):
            lines = self._wrap_with_prefix(
                prefix, sentence, usable // self.FONT_ADVANCE[font])
            block = len(lines) * row_h - (row_h - self.FONT_HEIGHT[font])
            if block <= height - 2 * 12:
                break

        y0 = (height - block) // 2
        adv = self.FONT_ADVANCE[font]
        for i, line in enumerate(lines):
            y = y0 + i * row_h
            if i == 0:
                # Signal word in bold: struck twice, a dot apart.
                for dx in (0, 1):
                    cmds.append(f'TEXT {text_x + dx},{y},"{font}",0,1,1,"{prefix}"')
                rest = line[len(prefix):].lstrip()
                if rest:
                    cmds.append(f'TEXT {text_x + (len(prefix) + 1) * adv},{y},'
                                f'"{font}",0,1,1,"{_tspl_safe(rest)}"')
            else:
                cmds.append(f'TEXT {text_x},{y},"{font}",0,1,1,"{_tspl_safe(line)}"')

        # Triangle centred on the text block.
        tri_y = max(4, y0 + (block - tri['height']) // 2)
        bitmap_cmd = (f'BITMAP {margin},{tri_y},{tri["width_bytes"]},'
                      f'{tri["height"]},0,').encode() + tri['data']

        cmds.append(f"PRINT {quantity},1")
        cmds.append("")

        # Join text commands, then splice the raw bitmap bytes in before PRINT.
        head = "\r\n".join(cmds[:-2]).encode('utf-8') + b"\r\n"
        tail = "\r\n".join(cmds[-2:]).encode('utf-8')
        return head + bitmap_cmd + b"\r\n" + tail

    # Glyph heights in dots, for vertical layout.
    FONT_HEIGHT = {"1": 12, "2": 20, "3": 24, "4": 32, "5": 48}

    @staticmethod
    def _wrap_with_prefix(prefix: str, text: str, width: int) -> list:
        """Word-wrap `prefix + " " + text` to `width` characters a line.

        Words are never broken -- www.P65Warnings.ca.gov in particular must
        stay whole -- so a word longer than the width gets a line to itself.
        """
        lines, line = [], prefix
        for word in text.split():
            if len(line) + 1 + len(word) <= width:
                line = f"{line} {word}"
            else:
                lines.append(line)
                line = word
        lines.append(line)
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

    def calibrate_media(self, stock) -> bool:
        """Mock calibration"""
        logger.info(f"Mock TSC printer: Would calibrate for {stock} (GAPDETECT)")
        self.loaded_stock = tuple(stock)
        return True

    def print_labels(self, print_job: PrintJob) -> bool:
        """Mock label printing"""
        logger.info(f"Mock TSC printer: Would print {print_job.quantity} label(s)")
        logger.info(f"  Template: {print_job.template}")
        logger.info(f"  Data: {print_job.data}")

        # Same table as the real printer, so the two cannot drift -- the mock
        # was silently missing box_label and shelf_label while the real one
        # had them.
        if print_job.template in TSCLabelPrinter.TEMPLATES:
            logger.debug(f"Mock TSPL would be generated for {print_job.template}")
        else:
            logger.error(f"Unknown template: {print_job.template}")
            return False

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
