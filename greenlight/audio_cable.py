"""
AudioCable class for object-oriented cable operations.

This module provides an OOP interface for working with individual audio cable instances,
separate from the CableType class which represents SKUs/product types.
"""

from greenlight.db import pg_pool


class AudioCable:
    """
    Represents an individual audio cable instance with test results and metadata.

    This class provides OOP methods for loading, creating, and updating cable records
    in the audio_cables table. Each instance represents a physical cable with a unique
    serial number.

    Attributes:
        serial_number: Unique identifier for the cable (e.g., "SD000123" or scanned barcode)
        sku: Cable type SKU (foreign key to cable_skus table)
        resistance_adc: Raw ADC value from resistance test
        operator: Operator who tested/registered the cable
        arduino_unit_id: ID of Arduino unit used for testing
        notes: Additional notes about the cable
        test_timestamp: When the cable was tested

        # Additional fields from joined cable_skus table (read-only)
        series: Cable series name
        length: Cable length
        color_pattern: Cable color pattern
        connector_type: Connector type
        core_cable: Core cable specification
        braid_material: Braid material specification
        description: Cable description
    """

    def __init__(self, serial_number=None):
        """
        Initialize an AudioCable instance.

        Args:
            serial_number: If provided, attempts to load cable data from database
        """
        # Core cable properties (from audio_cables table)
        self.serial_number = None
        self.sku = None
        self.resistance_adc = None
        self.operator = None
        self.arduino_unit_id = None
        self.notes = None
        self.test_timestamp = None

        # Extended properties from cable_skus join (read-only)
        self.series = None
        self.length = None
        self.color_pattern = None
        self.connector_type = None
        self.core_cable = None
        self.braid_material = None
        self.description = None

        # Registration code for wholesale/reseller cables
        self.registration_code = None

        # Load data if serial number provided
        if serial_number:
            self.load(serial_number)

    def __repr__(self):
        if self.serial_number:
            return f"<AudioCable {self.serial_number} - {self.sku or 'No SKU'}>"
        return "<AudioCable (not loaded)>"

    def load(self, serial_number):
        """
        Load cable data from database by serial number.

        Fetches cable record from audio_cables table and joins with cable_skus
        to get complete cable information.

        Args:
            serial_number: Serial number to look up

        Raises:
            ValueError: If serial number not found in database
        """
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ac.serial_number, ac.sku, ac.resistance_adc,
                           ac.operator, ac.arduino_unit_id, ac.notes, ac.test_timestamp,
                           ac.registration_code,
                           cs.series, cs.length, cs.color_pattern, cs.connector_type,
                           cs.core_cable, cs.braid_material, cs.description
                    FROM audio_cables ac
                    LEFT JOIN cable_skus cs ON ac.sku = cs.sku
                    WHERE ac.serial_number = %s
                """, (serial_number,))

                row = cur.fetchone()
                if not row:
                    raise ValueError(f"Serial number {serial_number} not found in database")

                # Map database columns to instance attributes
                colnames = [desc[0] for desc in cur.description]
                cable_data = dict(zip(colnames, row))

                # Populate core properties
                self.serial_number = cable_data.get('serial_number')
                self.sku = cable_data.get('sku')
                self.resistance_adc = cable_data.get('resistance_adc')
                self.operator = cable_data.get('operator')
                self.arduino_unit_id = cable_data.get('arduino_unit_id')
                self.notes = cable_data.get('notes')
                self.test_timestamp = cable_data.get('test_timestamp')
                self.registration_code = cable_data.get('registration_code')

                # Populate extended properties from cable_skus
                self.series = cable_data.get('series')
                self.length = cable_data.get('length')
                self.color_pattern = cable_data.get('color_pattern')
                self.connector_type = cable_data.get('connector_type')
                self.core_cable = cable_data.get('core_cable')
                self.braid_material = cable_data.get('braid_material')
                self.description = cable_data.get('description')

        finally:
            pg_pool.putconn(conn)

    def save(self):
        """
        Save a new cable record to the database.

        Inserts this cable instance as a new record in the audio_cables table.
        The serial_number and sku attributes must be set before calling save().

        Returns:
            dict: Result with 'success' boolean and 'timestamp' if successful,
                  or 'error' and 'message' if failed

        Raises:
            ValueError: If serial_number or sku is not set
        """
        if not self.serial_number:
            raise ValueError("serial_number must be set before saving")
        if not self.sku:
            raise ValueError("sku must be set before saving")

        conn = pg_pool.getconn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # Check for duplicate serial number
                    cur.execute(
                        "SELECT serial_number FROM audio_cables WHERE serial_number = %s",
                        (self.serial_number,)
                    )
                    if cur.fetchone():
                        return {
                            'success': False,
                            'error': 'duplicate',
                            'message': f'Serial number {self.serial_number} already exists'
                        }

                    # Insert new cable record
                    cur.execute("""
                        INSERT INTO audio_cables
                            (serial_number, sku, resistance_adc,
                             operator, arduino_unit_id, notes)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING test_timestamp
                    """, (
                        self.serial_number,
                        self.sku,
                        self.resistance_adc,
                        self.operator,
                        self.arduino_unit_id,
                        self.notes
                    ))

                    result = cur.fetchone()
                    conn.commit()

                    # Update local timestamp
                    self.test_timestamp = result[0]

                    return {
                        'success': True,
                        'timestamp': result[0]
                    }

        except Exception as e:
            conn.rollback()
            return {
                'success': False,
                'error': 'database',
                'message': str(e)
            }
        finally:
            pg_pool.putconn(conn)

    def update(self):
        """
        Update existing cable record in the database.

        Updates the database record matching this cable's serial_number with
        current property values. Typically used to add test results to a
        previously registered cable.

        Returns:
            dict: Result with 'success' boolean and 'timestamp' if successful,
                  or 'error' and 'message' if failed

        Raises:
            ValueError: If serial_number is not set
        """
        if not self.serial_number:
            raise ValueError("serial_number must be set before updating")

        conn = pg_pool.getconn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # Update cable record
                    cur.execute("""
                        UPDATE audio_cables
                        SET sku = %s,
                            resistance_adc = %s,
                            operator = %s,
                            arduino_unit_id = %s,
                            notes = %s,
                            test_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING test_timestamp
                    """, (
                        self.sku,
                        self.resistance_adc,
                        self.operator,
                        self.arduino_unit_id,
                        self.notes,
                        self.serial_number
                    ))

                    result = cur.fetchone()
                    if not result:
                        return {
                            'success': False,
                            'error': 'not_found',
                            'message': f'Serial number {self.serial_number} not found'
                        }

                    conn.commit()

                    # Update local timestamp
                    self.test_timestamp = result[0]

                    return {
                        'success': True,
                        'timestamp': result[0]
                    }

        except Exception as e:
            conn.rollback()
            return {
                'success': False,
                'error': 'database',
                'message': str(e)
            }
        finally:
            pg_pool.putconn(conn)

    def is_loaded(self):
        """Check if cable data has been loaded from database."""
        return self.serial_number is not None

    def has_test_results(self):
        """Check if cable has test results recorded."""
        return self.resistance_adc is not None

    def get_display_name(self):
        """
        Get a human-readable display name for the cable.

        Returns:
            str: Formatted cable name with series, length, and color
        """
        if not self.is_loaded():
            return "Not loaded"

        if self.series and self.length and self.color_pattern:
            name = f"{self.series} {self.length}ft {self.color_pattern}"
            if self.connector_type and self.connector_type.startswith("RA"):
                name += " (RA)"
            return name

        return self.sku or "Unknown cable"

    def get_display_info(self):
        """
        Get formatted display information for UI.

        Returns:
            str: Multi-line formatted string with cable details
        """
        if not self.is_loaded():
            return "No cable loaded"

        info_lines = [
            f"Serial Number: {self.serial_number}",
            f"SKU: {self.sku or 'N/A'}",
            f"Name: {self.get_display_name()}",
            ""
        ]

        # Test results section
        if self.has_test_results():
            info_lines.extend([
                "Test Results:",
                f"  Resistance: PASS (ADC: {self.resistance_adc})",
                f"  Operator: {self.operator or 'N/A'}",
                f"  Arduino Unit: {self.arduino_unit_id or 'N/A'}",
                f"  Test Date: {self.test_timestamp or 'N/A'}",
                ""
            ])
        else:
            info_lines.extend([
                "Test Results: Not tested yet",
                ""
            ])

        # Cable specifications (if available from join)
        if self.series:
            info_lines.extend([
                "Specifications:",
                f"  Series: {self.series}",
                f"  Length: {self.length} ft",
                f"  Color: {self.color_pattern}",
                f"  Connector: {self.connector_type}",
                f"  Core Cable: {self.core_cable}",
                f"  Braid Material: {self.braid_material}",
            ])
            if self.description:
                info_lines.append(f"  Description: {self.description}")

        if self.registration_code:
            info_lines.extend([
                "",
                "Registration:",
                f"  Code: {self.registration_code}",
            ])

        if self.notes:
            info_lines.extend([
                "",
                f"Notes: {self.notes}"
            ])

        return "\n".join(info_lines)
