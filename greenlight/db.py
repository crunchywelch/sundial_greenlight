import psycopg2
from psycopg2 import pool
import os

from greenlight.config import DB_CONFIG

pg_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    **DB_CONFIG
)

def insert_test_result(serial, resistance_adc, operator=None, source_node=None):
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO test_results
                        (serial, resistance_adc, operator, source_node)
                    VALUES (%s, %s, %s, %s)
                """, (serial, resistance_adc, operator, source_node))
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
                        (serial_number, sku, resistance_adc,
                         operator, arduino_unit_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING serial_number, test_timestamp
                """, (
                    serial_number, cable_type.sku, test_result.resistance_adc,
                    test_result.operator,
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
    """Get audio cable record by serial number

    For length: uses cable-specific length (ac.length) if set,
    otherwise falls back to SKU default (cs.length)
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku, ac.resistance_adc, ac.test_passed,
                       ac.operator, ac.arduino_unit_id, ac.notes, ac.test_timestamp,
                       ac.shopify_gid, ac.updated_timestamp, ac.description,
                       ac.registration_code,
                       cs.series, COALESCE(ac.length, CAST(cs.length AS REAL)) as length,
                       cs.color_pattern, cs.connector_type,
                       cs.core_cable, cs.braid_material
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

def register_scanned_cable(serial_number, cable_sku, operator=None, update_if_exists=False, description=None, length=None):
    """Register a cable with a scanned serial number into the database (intake workflow)

    Args:
        serial_number: The serial number from the cable label
        cable_sku: The SKU code for the cable
        operator: Operator ID who registered the cable
        update_if_exists: If True, update existing cable records
        description: Optional custom description (required for MISC SKUs)
        length: Optional custom length in feet (for MISC cables with variable lengths)
    """
    conn = pg_pool.getconn()
    try:
        # Format serial number (pad to 6 digits)
        formatted_serial = format_serial_number(serial_number)

        with conn:
            with conn.cursor() as cur:
                # Check if serial number already exists
                cur.execute("""
                    SELECT serial_number, sku, operator, updated_timestamp, notes
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
                        # Update existing record (include description and length if provided)
                        cur.execute("""
                            UPDATE audio_cables
                            SET sku = %s,
                                operator = %s,
                                updated_timestamp = CURRENT_TIMESTAMP,
                                description = COALESCE(%s, description),
                                length = COALESCE(%s, length),
                                notes = %s
                            WHERE serial_number = %s
                            RETURNING serial_number, updated_timestamp
                        """, (cable_sku, operator, description, length, 'Updated via scan', formatted_serial))
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
                        (serial_number, sku, resistance_adc,
                         operator, arduino_unit_id, description, length, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING serial_number, updated_timestamp
                """, (formatted_serial, cable_sku, None, operator, None, description, length, 'Scanned intake'))
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

def update_cable_test_results(serial_number, test_passed, resistance_adc=None, operator=None, arduino_unit_id=None):
    """Update an existing cable record with test results

    Args:
        serial_number: Cable serial number
        test_passed: Whether the cable passed all tests
        resistance_adc: Raw ADC value from resistance test
        operator: Operator ID who ran the test
        arduino_unit_id: Arduino tester unit ID
    """
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET test_passed = %s,
                        resistance_adc = %s,
                        operator = %s,
                        arduino_unit_id = %s,
                        test_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s
                    RETURNING test_timestamp
                """, (
                    test_passed, resistance_adc, operator, arduino_unit_id, serial_number
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


def assign_cable_to_customer(serial_number, customer_shopify_gid):
    """Assign a cable to a customer by updating the shopify_gid field"""
    conn = pg_pool.getconn()
    try:
        # Format serial number
        formatted_serial = format_serial_number(serial_number)

        with conn:
            with conn.cursor() as cur:
                # Check if cable exists
                cur.execute("""
                    SELECT serial_number, sku, shopify_gid
                    FROM audio_cables
                    WHERE serial_number = %s
                """, (formatted_serial,))
                existing = cur.fetchone()

                if not existing:
                    return {
                        'error': 'not_found',
                        'message': f'Cable with serial number {formatted_serial} not found in database'
                    }

                # Check if cable is already assigned
                if existing[2]:  # shopify_gid already set
                    return {
                        'error': 'already_assigned',
                        'message': f'Cable {formatted_serial} is already assigned to customer {existing[2]}',
                        'existing_customer_gid': existing[2]
                    }

                # Update cable with customer ID
                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = %s
                    WHERE serial_number = %s
                    RETURNING serial_number, sku, shopify_gid
                """, (customer_shopify_gid, formatted_serial))
                result = cur.fetchone()
                conn.commit()

                return {
                    'success': True,
                    'serial_number': result[0],
                    'sku': result[1],
                    'customer_gid': result[2]
                }
    except Exception as e:
        print(f"❌ Error assigning cable to customer: {e}")
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def get_cables_for_customer(customer_shopify_gid):
    """Get all cables assigned to a customer"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku, ac.updated_timestamp, ac.description,
                       cs.series, COALESCE(ac.length, CAST(cs.length AS REAL)) as length,
                       cs.color_pattern, cs.connector_type
                FROM audio_cables ac
                JOIN cable_skus cs ON ac.sku = cs.sku
                WHERE ac.shopify_gid = %s
                ORDER BY ac.updated_timestamp DESC
            """, (customer_shopify_gid,))
            rows = cur.fetchall()

            cables = []
            for row in rows:
                cables.append({
                    'serial_number': row[0],
                    'sku': row[1],
                    'updated_timestamp': row[2],
                    'description': row[3],
                    'series': row[4],
                    'length': row[5],
                    'color_pattern': row[6],
                    'connector_type': row[7]
                })
            return cables
    except Exception as e:
        print(f"❌ Error fetching cables for customer: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def get_all_cables(limit=100, offset=0):
    """Get all cables ordered by serial number descending (highest first)"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku, ac.updated_timestamp, ac.test_timestamp,
                       ac.resistance_adc, ac.test_passed, ac.operator, ac.shopify_gid,
                       ac.description,
                       cs.series, COALESCE(ac.length, CAST(cs.length AS REAL)) as length,
                       cs.color_pattern, cs.connector_type
                FROM audio_cables ac
                JOIN cable_skus cs ON ac.sku = cs.sku
                ORDER BY ac.serial_number DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = cur.fetchall()

            cables = []
            for row in rows:
                cables.append({
                    'serial_number': row[0],
                    'sku': row[1],
                    'updated_timestamp': row[2],
                    'test_timestamp': row[3],
                    'resistance_adc': row[4],
                    'test_passed': row[5],
                    'operator': row[6],
                    'shopify_gid': row[7],
                    'description': row[8],
                    'series': row[9],
                    'length': row[10],
                    'color_pattern': row[11],
                    'connector_type': row[12]
                })
            return cables
    except Exception as e:
        print(f"❌ Error fetching all cables: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def get_cable_count():
    """Get total count of cables in database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM audio_cables")
            return cur.fetchone()[0]
    except Exception as e:
        print(f"❌ Error getting cable count: {e}")
        return 0
    finally:
        pg_pool.putconn(conn)

def get_available_inventory(series=None):
    """Get count of cables available to sell (not assigned to customer) grouped by SKU

    Args:
        series: Optional series filter (e.g., 'Standard', 'Signature', 'MISC')

    Note: For MISC SKUs, inventory is not grouped since each cable has unique attributes.
    MISC cables are listed individually with their custom lengths and descriptions.
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            # For MISC series, show individual cables with their custom attributes
            if series and 'misc' in series.lower():
                query = """
                    SELECT
                        ac.sku,
                        cs.series,
                        COALESCE(ac.length, CAST(cs.length AS REAL)) as length,
                        cs.color_pattern,
                        cs.connector_type,
                        ac.description,
                        1 as available_count
                    FROM audio_cables ac
                    JOIN cable_skus cs ON ac.sku = cs.sku
                    WHERE cs.series = %s
                        AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                    ORDER BY ac.length, ac.description
                """
                cur.execute(query, [series])
            else:
                # For regular SKUs, group by SKU attributes
                query = """
                    SELECT
                        cs.sku,
                        cs.series,
                        cs.length,
                        cs.color_pattern,
                        cs.connector_type,
                        cs.description,
                        COUNT(ac.serial_number) as available_count
                    FROM cable_skus cs
                    LEFT JOIN audio_cables ac ON cs.sku = ac.sku
                        AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                """

                params = []
                if series:
                    query += " WHERE cs.series = %s"
                    params.append(series)

                query += """
                    GROUP BY cs.sku, cs.series, cs.length, cs.color_pattern, cs.connector_type, cs.description
                    HAVING COUNT(ac.serial_number) > 0
                    ORDER BY cs.length, cs.color_pattern, cs.connector_type
                """
                cur.execute(query, params)

            rows = cur.fetchall()

            inventory = []
            for row in rows:
                inventory.append({
                    'sku': row[0],
                    'series': row[1],
                    'length': row[2],
                    'color_pattern': row[3],
                    'connector_type': row[4],
                    'description': row[5],
                    'available_count': row[6]
                })
            return inventory
    except Exception as e:
        print(f"❌ Error fetching available inventory: {e}")
        return []
    finally:
        pg_pool.putconn(conn)

def assign_registration_code(serial_number, code):
    """Assign a registration code to a cable for wholesale/reseller sales.

    Args:
        serial_number: Cable serial number
        code: Registration code (format: XXXX-XXXX)

    Returns:
        dict with 'success' bool, or 'error'/'message' on failure
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET registration_code = %s
                    WHERE serial_number = %s
                    RETURNING serial_number, registration_code
                """, (code, formatted_serial))
                result = cur.fetchone()
                conn.commit()
                if result:
                    return {'success': True, 'serial_number': result[0], 'registration_code': result[1]}
                return {'error': 'not_found', 'message': f'Cable {formatted_serial} not found'}
    except Exception as e:
        conn.rollback()
        error_msg = str(e)
        if 'unique' in error_msg.lower() or 'duplicate' in error_msg.lower():
            return {'error': 'duplicate_code', 'message': f'Registration code {code} already in use'}
        return {'error': 'database', 'message': error_msg}
    finally:
        pg_pool.putconn(conn)


def batch_assign_registration_codes(serial_numbers):
    """Generate and assign registration codes to a list of cables in a single transaction.

    Retries with new codes on collision (up to 3 attempts per cable).

    Args:
        serial_numbers: List of cable serial numbers

    Returns:
        dict with:
            'success': bool
            'results': list of {serial_number, registration_code} dicts
            'errors': list of {serial_number, error} dicts
    """
    from greenlight.registration import generate_registration_code

    conn = pg_pool.getconn()
    results = []
    errors = []
    try:
        with conn:
            with conn.cursor() as cur:
                for serial in serial_numbers:
                    formatted_serial = format_serial_number(serial)
                    assigned = False
                    for attempt in range(3):
                        code = generate_registration_code()
                        try:
                            cur.execute("""
                                UPDATE audio_cables
                                SET registration_code = %s
                                WHERE serial_number = %s AND registration_code IS NULL
                                RETURNING serial_number, registration_code
                            """, (code, formatted_serial))
                            result = cur.fetchone()
                            if result:
                                results.append({
                                    'serial_number': result[0],
                                    'registration_code': result[1]
                                })
                                assigned = True
                                break
                            else:
                                # Cable not found or already has a code
                                cur.execute(
                                    "SELECT registration_code FROM audio_cables WHERE serial_number = %s",
                                    (formatted_serial,)
                                )
                                existing = cur.fetchone()
                                if existing and existing[0]:
                                    errors.append({
                                        'serial_number': formatted_serial,
                                        'error': f'Already has code: {existing[0]}'
                                    })
                                else:
                                    errors.append({
                                        'serial_number': formatted_serial,
                                        'error': 'Cable not found'
                                    })
                                assigned = True  # Don't retry
                                break
                        except Exception as e:
                            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                                # Code collision, retry with new code
                                conn.rollback()
                                continue
                            raise
                    if not assigned:
                        errors.append({
                            'serial_number': formatted_serial,
                            'error': 'Failed after 3 code generation attempts'
                        })
                conn.commit()
        return {'success': len(errors) == 0, 'results': results, 'errors': errors}
    except Exception as e:
        conn.rollback()
        return {'success': False, 'results': results, 'errors': errors,
                'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def get_available_series():
    """Get list of product series that have available inventory"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT cs.series
                FROM cable_skus cs
                LEFT JOIN audio_cables ac ON cs.sku = ac.sku
                    AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                WHERE ac.serial_number IS NOT NULL
                ORDER BY cs.series
            """)
            rows = cur.fetchall()
            return [row[0] for row in rows if row[0]]
    except Exception as e:
        print(f"❌ Error fetching available series: {e}")
        return []
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
                resistance_adc INTEGER,
                operator TEXT,
                source_node TEXT,
                label_version TEXT,
                notes TEXT,
                timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)

if __name__ == "__main__":
    init_pg_schema()
