import psycopg2
from psycopg2 import pool
import os

from greenlight.config import DB_CONFIG

pg_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    **DB_CONFIG
)

def insert_test_result(serial, resistance, capacitance, operator=None, source_node=None):
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO test_results 
                        (serial, resistance_ohms, capacitance_pf, operator, source_node)
                    VALUES (%s, %s, %s, %s, %s)
                """, (serial, resistance, capacitance, operator, source_node))
            conn.commit()
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)

def generate_serial_number():
    """Generate next sequential serial number for produced cables"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            # Get the next serial number from sequence
            cur.execute("SELECT nextval('audio_cable_serial_seq')")
            serial_num = cur.fetchone()[0]
            return f"SD{serial_num:06d}"  # Format: SD000001, SD000002, etc.
    except Exception as e:
        print(f"❌ Error generating serial number: {e}")
        return None
    finally:
        pg_pool.putconn(conn)

def insert_audio_cable(cable_type, test_result):
    """Insert a cable that passed testing into the audio_cables table"""
    conn = pg_pool.getconn()
    try:
        serial_number = generate_serial_number()
        if not serial_number:
            raise Exception("Failed to generate serial number")
            
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO audio_cables 
                        (serial_number, sku, resistance_ohms, capacitance_pf, 
                         operator, arduino_unit_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING serial_number, test_timestamp
                """, (
                    serial_number, cable_type.sku, test_result.resistance_ohms, 
                    test_result.capacitance_pf, test_result.operator, 
                    test_result.arduino_unit_id, None  # notes can be added later
                ))
                result = cur.fetchone()
                conn.commit()
                return {
                    'serial_number': result[0],
                    'timestamp': result[1],
                    'sku': cable_type.sku
                }
    except Exception as e:
        print(f"❌ Error inserting audio cable: {e}")
        conn.rollback()
        return None
    finally:
        pg_pool.putconn(conn)

def get_audio_cable(serial_number):
    """Get audio cable record by serial number"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku, ac.resistance_ohms, ac.capacitance_pf,
                       ac.operator, ac.arduino_unit_id, ac.notes, ac.test_timestamp,
                       cs.series, cs.length, cs.color_pattern, cs.connector_type,
                       cs.core_cable, cs.braid_material, cs.description
                FROM audio_cables ac
                JOIN cable_skus cs ON ac.sku = cs.sku
                WHERE ac.serial_number = %s
            """, (serial_number,))
            row = cur.fetchone()
            if row:
                colnames = [desc[0] for desc in cur.description]
                return dict(zip(colnames, row))
            return None
    except Exception as e:
        print(f"❌ Error fetching audio cable: {e}")
        return None
    finally:
        pg_pool.putconn(conn)

def format_serial_number(serial_number):
    """
    Format serial number by padding numeric portion to 6 digits.
    Examples:
        "123" -> "000123"
        "SD123" -> "SD000123"
        "000123" -> "000123" (already formatted)
    """
    import re

    # Extract prefix (letters) and numeric part
    match = re.match(r'^([A-Za-z]*)(\d+)$', serial_number)
    if match:
        prefix = match.group(1)
        number = match.group(2)
        # Pad numeric part to 6 digits
        padded_number = number.zfill(6)
        return f"{prefix}{padded_number}"

    # If doesn't match expected pattern, return as-is
    return serial_number

def register_scanned_cable(serial_number, cable_sku, operator=None, update_if_exists=False):
    """Register a cable with a scanned serial number into the database (intake workflow)"""
    conn = pg_pool.getconn()
    try:
        # Format serial number (pad to 6 digits)
        formatted_serial = format_serial_number(serial_number)

        with conn:
            with conn.cursor() as cur:
                # Check if serial number already exists
                cur.execute("""
                    SELECT serial_number, sku, operator, test_timestamp, notes
                    FROM audio_cables
                    WHERE serial_number = %s
                """, (formatted_serial,))
                existing = cur.fetchone()

                if existing:
                    if not update_if_exists:
                        # Return duplicate error with existing record info
                        return {
                            'error': 'duplicate',
                            'message': f'Serial number {formatted_serial} already exists in database',
                            'existing_record': {
                                'serial_number': existing[0],
                                'sku': existing[1],
                                'operator': existing[2],
                                'timestamp': existing[3],
                                'notes': existing[4]
                            }
                        }
                    else:
                        # Update existing record
                        cur.execute("""
                            UPDATE audio_cables
                            SET sku = %s,
                                operator = %s,
                                test_timestamp = CURRENT_TIMESTAMP,
                                notes = %s
                            WHERE serial_number = %s
                            RETURNING serial_number, test_timestamp
                        """, (cable_sku, operator, 'Updated via scan', formatted_serial))
                        result = cur.fetchone()
                        conn.commit()
                        return {
                            'serial_number': result[0],
                            'timestamp': result[1],
                            'sku': cable_sku,
                            'success': True,
                            'updated': True
                        }

                # Insert new cable record with scanned serial number
                cur.execute("""
                    INSERT INTO audio_cables
                        (serial_number, sku, resistance_ohms, capacitance_pf,
                         operator, arduino_unit_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING serial_number, test_timestamp
                """, (formatted_serial, cable_sku, None, None, operator, None, 'Scanned intake'))
                result = cur.fetchone()
                conn.commit()
                return {
                    'serial_number': result[0],
                    'timestamp': result[1],
                    'sku': cable_sku,
                    'success': True
                }
    except Exception as e:
        print(f"❌ Error registering scanned cable: {e}")
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)

def update_cable_test_results(serial_number, test_result):
    """Update an existing cable record with test results"""
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET resistance_ohms = %s,
                        capacitance_pf = %s,
                        operator = %s,
                        arduino_unit_id = %s,
                        test_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s
                    RETURNING test_timestamp
                """, (
                    test_result.resistance_ohms, test_result.capacitance_pf,
                    test_result.operator, test_result.arduino_unit_id, serial_number
                ))
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else None
    except Exception as e:
        print(f"❌ Error updating cable test results: {e}")
        conn.rollback()
        return None
    finally:
        pg_pool.putconn(conn)

def init_db():
    conn = pg_pool.getconn()
    with conn.cursor() as cur:
        cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'cable_type') THEN
                        CREATE TYPE cable_type AS ENUM ('TS', 'TRS', 'XLR');
                    END IF;
                END$$;
            """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audio_cables (
                id SERIAL PRIMARY KEY,
                cable_type cable_type NOT NULL,
                serial TEXT UNIQUE NOT NULL,
                resistance_ohms REAL NOT NULL,
                capacitance_pf REAL NOT NULL,
                operator TEXT,
                source_node TEXT,
                label_version TEXT,
                notes TEXT,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

if __name__ == "__main__":
    init_pg_schema()
