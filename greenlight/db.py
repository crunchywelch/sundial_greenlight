import logging
import os
import re

import psycopg2
from psycopg2 import pool

from greenlight.config import DB_CONFIG

logger = logging.getLogger(__name__)

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
        logger.error("Error inserting test result: %s", e)
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
        logger.error("Error generating serial number: %s", e)
        return None
    finally:
        pg_pool.putconn(conn)

def get_audio_cable(serial_number):
    """Get audio cable record by serial number."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.length, ac.connector_code,
                       ac.resistance_adc, ac.calibration_adc,
                       ac.resistance_adc_p3, ac.calibration_adc_p3, ac.test_passed,
                       ac.operator, ac.arduino_unit_id, ac.notes, ac.test_timestamp,
                       ac.shopify_gid, ac.updated_timestamp,
                       sg.description, sg.archived_at,
                       ac.registration_code
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.serial_number = %s
            """, (serial_number,))
            row = cur.fetchone()
            if row:
                colnames = [desc[0] for desc in cur.description]
                return _enrich_record(dict(zip(colnames, row)))
            return None
    except Exception as e:
        logger.error("Error fetching audio cable: %s", e)
        return None
    finally:
        pg_pool.putconn(conn)

def validate_serial_number(serial_number):
    """Check that a serial number is purely numeric.

    Returns:
        (True, None) if valid, (False, error_message) if invalid.
    """
    if not serial_number or not serial_number.strip():
        return False, "Serial number is empty"
    s = serial_number.strip()
    if not s.isdigit():
        return False, f"Invalid serial number '{s}' — must be numeric"
    return True, None


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

def register_scanned_cable(serial_number, sku_group, length, connector_code,
                           operator=None, update_if_exists=False):
    """Register a cable with a scanned serial number (Phase 4 intake workflow).

    Args:
        serial_number: The serial number from the cable label
        sku_group: The sku_group identifier (e.g. 'SC-GL', 'SC-MISC-42',
            'SC-LTD-PHISH26'). For catalog this is `{prefix}-{pattern_code}`;
            for MISC/LTD this is the unique group SKU.
        length: Cable length in feet (numeric)
        connector_code: Connector code per the YAML connectors[] list —
            '' for straight, '-R' for right angle (catalog cables); MISC/LTD
            cables also carry a connector_code on audio_cables.
        operator: Operator ID who registered the cable
        update_if_exists: If True, update existing cable records
    """
    if length is None:
        return {'error': 'invalid_length', 'message': 'length is required'}
    if connector_code is None:
        connector_code = ''

    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)

        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT serial_number, sku_group, length, connector_code,
                           operator, updated_timestamp, notes
                    FROM audio_cables
                    WHERE serial_number = %s
                """, (formatted_serial,))
                existing = cur.fetchone()

                if existing:
                    if not update_if_exists:
                        return {
                            'error': 'duplicate',
                            'message': f'Serial number {formatted_serial} already exists in database',
                            'existing_record': {
                                'serial_number': existing[0],
                                'sku_group': existing[1],
                                'length': float(existing[2]) if existing[2] is not None else None,
                                'connector_code': existing[3],
                                'operator': existing[4],
                                'timestamp': existing[5],
                                'notes': existing[6],
                            }
                        }
                    cur.execute("""
                        UPDATE audio_cables
                        SET sku_group = %s,
                            length = %s,
                            connector_code = %s,
                            operator = %s,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number, updated_timestamp
                    """, (sku_group, length, connector_code, operator, formatted_serial))
                    result = cur.fetchone()
                    conn.commit()
                    return {
                        'serial_number': result[0],
                        'timestamp': result[1],
                        'sku_group': sku_group,
                        'length': float(length),
                        'connector_code': connector_code,
                        'success': True,
                        'updated': True,
                    }

                # Insert new cable record
                cur.execute("""
                    INSERT INTO audio_cables
                        (serial_number, sku_group, length, connector_code,
                         resistance_adc, operator, arduino_unit_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING serial_number, updated_timestamp
                """, (formatted_serial, sku_group, length, connector_code,
                      None, operator, None, 'Scanned intake'))
                result = cur.fetchone()
                conn.commit()
                return {
                    'serial_number': result[0],
                    'timestamp': result[1],
                    'sku_group': sku_group,
                    'length': float(length),
                    'connector_code': connector_code,
                    'success': True,
                }
    except Exception as e:
        logger.error("Error registering scanned cable: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)

def update_cable_test_results(serial_number, test_passed, resistance_adc=None, calibration_adc=None,
                              resistance_adc_p3=None, calibration_adc_p3=None,
                              operator=None, arduino_unit_id=None, notes=None):
    """Update an existing cable record with test results

    Args:
        serial_number: Cable serial number
        test_passed: Whether the cable passed all tests
        resistance_adc: Raw ADC value from resistance test (pin2 for XLR)
        calibration_adc: Calibration baseline ADC at time of test (pin2 for XLR)
        resistance_adc_p3: Pin 3 raw ADC value (XLR only)
        calibration_adc_p3: Pin 3 calibration baseline ADC (XLR only)
        operator: Operator ID who ran the test
        arduino_unit_id: Arduino tester unit ID
        notes: Test failure reason or other notes
    """
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET test_passed = %s,
                        resistance_adc = %s,
                        calibration_adc = %s,
                        resistance_adc_p3 = %s,
                        calibration_adc_p3 = %s,
                        operator = %s,
                        arduino_unit_id = %s,
                        notes = %s,
                        test_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s
                    RETURNING test_timestamp
                """, (
                    test_passed, resistance_adc, calibration_adc,
                    resistance_adc_p3, calibration_adc_p3,
                    operator, arduino_unit_id, notes, serial_number
                ))
                result = cur.fetchone()
                conn.commit()
                return result[0] if result else None
    except Exception as e:
        logger.error("Error updating cable test results: %s", e)
        conn.rollback()
        return None
    finally:
        pg_pool.putconn(conn)


_LTD_SLUG_PATTERN = re.compile(r'^[A-Z0-9]{4,12}$')


def sku_kind(sku):
    """Classify a SKU (variant or group) by pattern.

    Tries variant SKU first ('SC-12GL', 'SC-12GL-R'), then group SKU
    ('SC-GL', 'SC-MISC-42', 'SC-LTD-PHISH26'). Returns 'catalog', 'misc',
    or 'ltd'. Unrecognized inputs default to 'catalog' (matches the Phase 3
    permissive behavior for callers that pass arbitrary strings).
    """
    from greenlight.cable_config import parse_variant_sku, parse_group_sku
    if not sku:
        return 'catalog'
    parsed = parse_variant_sku(sku)
    if parsed.get('kind') is not None:
        return parsed['kind']
    parsed = parse_group_sku(sku)
    return parsed.get('kind') or 'catalog'


def _enrich_record(record):
    """Add resolver-derived fields to a cable record dict (Phase 4).

    Required input key: 'sku_group'. Optional: 'length', 'connector_code',
    'description', 'archived_at'. Mutates record in place and returns it.

    Populates from the resolver:
      - kind, prefix, series
      - pattern_code, pattern_name (catalog only; None for MISC/LTD)
      - connector_display (looked up from prefix + connector_code)
      - core_cable, braid_material (series-level from YAML)
      - variant_sku — the user-facing SKU string Shopify uses

    Backward-compat aliases (deprecated; new code should use the canonical
    fields above):
      - sku ← variant_sku           (for display callers)
      - color_pattern ← pattern_name
      - connector_type ← connector_display
    """
    from greenlight.cable_config import (
        parse_group_sku, format_variant_sku, series_data_for_prefix,
        connector_display_for,
    )
    sku_group = record.get('sku_group')
    parsed = parse_group_sku(sku_group)
    kind = parsed.get('kind')
    prefix = parsed.get('prefix')

    record['kind'] = kind
    record['prefix'] = prefix
    record['series'] = parsed.get('series')

    if kind == 'catalog':
        record['pattern_code'] = parsed.get('pattern_code')
        record['pattern_name'] = parsed.get('pattern_name')
    else:
        record['pattern_code'] = None
        record['pattern_name'] = None

    # Length lives on audio_cables.length now (NUMERIC(5,2) → Decimal).
    # Coerce to float so consumers see a stable type.
    raw_length = record.get('length')
    if raw_length is not None:
        try:
            record['length'] = float(raw_length)
        except (TypeError, ValueError):
            pass  # leave as-is

    # Connector display: resolved from prefix + connector_code (the latter
    # lives on audio_cables for every cable, not just catalog).
    connector_code = record.get('connector_code') or ''
    record['connector_code'] = connector_code
    record['connector_display'] = (
        connector_display_for(prefix, connector_code) if prefix else None
    )

    # Series-level construction (same for every cable in a series)
    series_data = series_data_for_prefix(prefix) if prefix else None
    if series_data:
        record['core_cable'] = series_data.get('core_cable')
        record['braid_material'] = series_data.get('braid_material')
    else:
        record['core_cable'] = None
        record['braid_material'] = None

    # The user-facing variant SKU — what gets printed on labels and shows in
    # Shopify. Catalog cables: '{prefix}-{length}{pattern}{connector}'.
    # MISC/LTD: same as the group SKU.
    record['variant_sku'] = format_variant_sku(
        group_sku=sku_group,
        length=record.get('length'),
        connector_code=connector_code,
    )

    # Backward-compat aliases
    record['sku'] = record['variant_sku']
    record['color_pattern'] = record['pattern_name']
    record['connector_type'] = record['connector_display']

    return record


def update_cable_description(serial_number, description):
    """Update the description for a MISC cable's sku_group row.

    This changes the description for ALL cables registered against the same
    MISC group. No-op (returns False) for non-MISC SKUs.

    Args:
        serial_number: Cable serial number
        description: New description text

    Returns:
        True if updated, False on error or if cable is not a MISC variant
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT sku_group FROM audio_cables
                    WHERE serial_number = %s
                """, (formatted_serial,))
                row = cur.fetchone()
                if not row or sku_kind(row[0]) != 'misc':
                    return False

                cur.execute("""
                    UPDATE sku_group
                    SET description = %s
                    WHERE sku = %s
                    RETURNING sku
                """, (description, row[0]))
                result = cur.fetchone()
                conn.commit()
                return result is not None
    except Exception as e:
        logger.error("Error updating cable description: %s", e)
        conn.rollback()
        return False
    finally:
        pg_pool.putconn(conn)


def get_or_create_misc_sku(series_prefix, description):
    """Look up or create a MISC sku_group.

    Dedupes by (series_prefix, description): same description in the same
    series shares one sku_group row. Length is per-cable (lives on
    audio_cables) so it's no longer part of group identity.

    Args:
        series_prefix: e.g. "SC", "TC"
        description: Free-form group description

    Returns:
        sku string, or None on error
    """
    from greenlight.cable_config import series_for_prefix

    if series_for_prefix(series_prefix) is None:
        logger.error("Unknown series prefix %s — no YAML config", series_prefix)
        return None

    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (series_prefix,)
                )

                cur.execute("""
                    SELECT sku FROM sku_group
                    WHERE sku LIKE %s
                      AND description = %s
                """, (f"{series_prefix}-MISC-%", description))
                existing = cur.fetchone()
                if existing:
                    return existing[0]

                cur.execute("SELECT nextval('cable_misc_variant_seq')")
                seq = cur.fetchone()[0]
                new_sku = f"{series_prefix}-MISC-{seq}"

                cur.execute("""
                    INSERT INTO sku_group (sku, description)
                    VALUES (%s, %s)
                """, (new_sku, description))
                conn.commit()
                return new_sku
    except Exception as e:
        logger.error("Error in get_or_create_misc_sku: %s", e)
        conn.rollback()
        return None
    finally:
        pg_pool.putconn(conn)


def ensure_catalog_sku_group(series_prefix, pattern_code):
    """Idempotently ensure a catalog sku_group row exists for the combo.

    Phase 4 design: catalog groups self-seed when a cable is registered with
    a previously-unseen (prefix, pattern_code) combo. The Phase 4 migration
    seeded the existing 14 combos; this helper handles future additions
    without requiring a schema migration each time.

    Returns the group sku string ('{prefix}-{pattern_code}'), or None on error.
    """
    from greenlight.cable_config import (
        series_for_prefix, pattern_for_code,
    )
    if series_for_prefix(series_prefix) is None:
        logger.error("Unknown series prefix %s", series_prefix)
        return None
    pattern = pattern_for_code(pattern_code)
    pattern_name = pattern.get('name') if pattern else None
    sku = f"{series_prefix}-{pattern_code}"

    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sku_group (sku, description)
                    VALUES (%s, %s)
                    ON CONFLICT (sku) DO NOTHING
                """, (sku, pattern_name))
                conn.commit()
        return sku
    except Exception as e:
        logger.error("Error ensuring catalog sku_group %s: %s", sku, e)
        conn.rollback()
        return None
    finally:
        pg_pool.putconn(conn)


def search_misc_variants(series_prefix):
    """Return recent MISC groups for a series prefix (for picker UI).

    Args:
        series_prefix: e.g. "SC", "TC"

    Returns:
        List of dicts with sku, description, cable_count
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sg.sku, sg.description,
                       (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
                FROM sku_group sg
                WHERE sg.sku LIKE %s
                  AND sg.sku ~ '-MISC-[0-9]+$'
                ORDER BY sg.sku DESC
                LIMIT 20
            """, (f"{series_prefix}-MISC-%",))
            rows = cur.fetchall()
            return [
                {'sku': r[0], 'description': r[1], 'cable_count': r[2]}
                for r in rows
            ]
    except Exception as e:
        logger.error("Error searching MISC groups: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def list_ltd_editions(active_only=True, series_prefix=None):
    """List LTD editions with cable counts (read-only; CRUD lives in shopify_app).

    Args:
        active_only: If True, exclude archived editions
        series_prefix: Optional filter (e.g. 'SC' to only show Studio Classic editions)

    Returns:
        List of dicts with sku, slug, event_name, series, length, description,
        active, cable_count, created_at.
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            params = []
            where_clauses = ["sg.sku ~ '-LTD-[A-Z0-9]{4,12}$'"]
            if active_only:
                where_clauses.append("sg.archived_at IS NULL")
            if series_prefix:
                where_clauses.append("sg.sku LIKE %s")
                params.append(f"{series_prefix}-LTD-%")

            where_sql = " AND ".join(where_clauses)
            cur.execute(f"""
                SELECT sg.sku, sg.description, sg.archived_at,
                       (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
                FROM sku_group sg
                WHERE {where_sql}
                ORDER BY (sg.archived_at IS NULL) DESC, sg.sku
            """, params)
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    'sku_group': r[0],
                    'sku': r[0],  # backward-compat alias for callers expecting 'sku'
                    'slug': r[0].rsplit('-', 1)[-1],
                    'description': r[1],
                    'archived_at': r[2],
                    'active': r[2] is None,
                    'cable_count': r[3],
                })
            return results
    except Exception as e:
        logger.error("Error listing LTD editions: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def get_ltd_edition(sku):
    """Fetch a single LTD edition by SKU (read-only).

    Returns dict with sku_group/sku, slug, description, archived_at, active,
    cable_count — or None. (Phase 4: cable_ltd_metadata is gone; description
    on sku_group carries what was previously event_name + notes.)
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sg.sku, sg.description, sg.archived_at,
                       (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
                FROM sku_group sg
                WHERE sg.sku = %s
            """, (sku,))
            row = cur.fetchone()
            if not row:
                return None
            return {
                'sku_group': row[0],
                'sku': row[0],
                'slug': row[0].rsplit('-', 1)[-1],
                'description': row[1],
                'archived_at': row[2],
                'active': row[2] is None,
                'cable_count': row[3],
            }
    except Exception as e:
        logger.error("Error fetching LTD edition %s: %s", sku, e)
        return None
    finally:
        pg_pool.putconn(conn)


def get_available_count_for_sku(sku):
    """Get count of available (passed + unassigned) cables for a SKU.

    The input may be either a variant SKU (e.g. 'SC-12GL', 'SC-12GL-R') or a
    group/MISC/LTD SKU. Catalog variants are split into (sku_group, length,
    connector_code) for the count; MISC/LTD/group inputs match all cables in
    that group regardless of length/connector.
    """
    from greenlight.cable_config import parse_variant_sku

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            parsed = parse_variant_sku(sku)
            kind = parsed.get('kind')
            if kind == 'catalog':
                cur.execute("""
                    SELECT COUNT(*)
                    FROM audio_cables ac
                    WHERE ac.test_passed = TRUE
                      AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                      AND ac.sku_group = %s
                      AND ac.length = %s
                      AND ac.connector_code = %s
                """, (parsed['group_sku'], parsed['length'], parsed.get('connector_code') or ''))
            else:
                # MISC/LTD/group string — count by sku_group
                cur.execute("""
                    SELECT COUNT(*)
                    FROM audio_cables ac
                    WHERE ac.test_passed = TRUE
                      AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                      AND ac.sku_group = %s
                """, (sku,))
            return cur.fetchone()[0]
    except Exception as e:
        logger.error("Error getting available count for SKU %s: %s", sku, e)
        return 0
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
                cur.execute("""
                    SELECT serial_number, sku_group, shopify_gid
                    FROM audio_cables
                    WHERE serial_number = %s
                """, (formatted_serial,))
                existing = cur.fetchone()

                if not existing:
                    return {
                        'error': 'not_found',
                        'message': f'Cable with serial number {formatted_serial} not found in database'
                    }

                if existing[2]:
                    return {
                        'error': 'already_assigned',
                        'message': f'Cable {formatted_serial} is already assigned to customer {existing[2]}',
                        'existing_customer_gid': existing[2]
                    }

                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = %s
                    WHERE serial_number = %s
                    RETURNING serial_number, sku_group, shopify_gid
                """, (customer_shopify_gid, formatted_serial))
                result = cur.fetchone()
                conn.commit()

                return {
                    'success': True,
                    'serial_number': result[0],
                    'sku_group': result[1],
                    'customer_gid': result[2]
                }
    except Exception as e:
        logger.error("Error assigning cable to customer: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def unassign_cable(serial_number):
    """Remove customer and order assignment from a cable, returning it to inventory.

    Returns:
        dict with 'success' or 'error'/'message'
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = NULL,
                        shopify_order_gid = NULL,
                        updated_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s AND shopify_gid IS NOT NULL
                    RETURNING serial_number
                """, (formatted_serial,))
                result = cur.fetchone()
                conn.commit()
                if result:
                    return {'success': True, 'serial_number': result[0]}
                return {'error': 'not_assigned', 'message': f'Cable {formatted_serial} is not assigned to anyone'}
    except Exception as e:
        logger.error("Error unassigning cable: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def force_reassign_cable(serial_number, customer_shopify_gid):
    """Unconditionally reassign a cable to a customer (overrides existing assignment)"""
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = %s
                    WHERE serial_number = %s
                    RETURNING serial_number, sku_group, shopify_gid
                """, (customer_shopify_gid, formatted_serial))
                result = cur.fetchone()
                conn.commit()

                if result:
                    return {
                        'success': True,
                        'serial_number': result[0],
                        'sku_group': result[1],
                        'customer_gid': result[2]
                    }
                return {
                    'error': 'not_found',
                    'message': f'Cable with serial number {formatted_serial} not found'
                }
    except Exception as e:
        logger.error("Error reassigning cable: %s", e)
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
                SELECT ac.serial_number, ac.sku_group, ac.length, ac.connector_code,
                       ac.updated_timestamp, sg.description, sg.archived_at
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.shopify_gid = %s
                ORDER BY ac.updated_timestamp DESC
            """, (customer_shopify_gid,))
            rows = cur.fetchall()

            cables = []
            for row in rows:
                cables.append(_enrich_record({
                    'serial_number': row[0],
                    'sku_group': row[1],
                    'length': row[2],
                    'connector_code': row[3],
                    'updated_timestamp': row[4],
                    'description': row[5],
                    'archived_at': row[6],
                }))
            return cables
    except Exception as e:
        logger.error("Error fetching cables for customer: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)

def get_all_cables(limit=100, offset=0):
    """Get all cables ordered by serial number descending (highest first)"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.length, ac.connector_code,
                       ac.updated_timestamp, ac.test_timestamp,
                       ac.resistance_adc, ac.test_passed, ac.operator, ac.shopify_gid,
                       sg.description
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                ORDER BY ac.serial_number DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))
            rows = cur.fetchall()

            cables = []
            for row in rows:
                cables.append(_enrich_record({
                    'serial_number': row[0],
                    'sku_group': row[1],
                    'length': row[2],
                    'connector_code': row[3],
                    'updated_timestamp': row[4],
                    'test_timestamp': row[5],
                    'resistance_adc': row[6],
                    'test_passed': row[7],
                    'operator': row[8],
                    'shopify_gid': row[9],
                    'description': row[10],
                }))
            return cables
    except Exception as e:
        logger.error("Error fetching all cables: %s", e)
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
        logger.error("Error getting cable count: %s", e)
        return 0
    finally:
        pg_pool.putconn(conn)

def get_available_inventory(series=None):
    """Get count of cables available to sell, grouped by variant.

    Phase 4: rolls up by (sku_group, length, connector_code) since the same
    sku_group can hold cables of different lengths/connectors. Each row in
    the result represents a distinct variant the operator can fulfill from.

    Args:
        series: Optional series filter (e.g., 'Studio Classic', 'Tour Classic')
    """
    from greenlight.cable_config import prefix_for_series

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            query = """
                SELECT
                    ac.sku_group,
                    ac.length,
                    ac.connector_code,
                    sg.description,
                    COUNT(*) as available_count
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.test_passed = TRUE
                  AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
            """
            params = []
            if series:
                prefix = prefix_for_series(series)
                if prefix is None:
                    return []
                query += " AND ac.sku_group LIKE %s"
                params.append(f"{prefix}-%")
            query += """
                GROUP BY ac.sku_group, ac.length, ac.connector_code, sg.description
                ORDER BY ac.sku_group, ac.length, ac.connector_code
            """
            cur.execute(query, params)
            rows = cur.fetchall()

            inventory = []
            for row in rows:
                enriched = _enrich_record({
                    'sku_group': row[0],
                    'length': row[1],
                    'connector_code': row[2],
                    'description': row[3],
                })
                enriched['available_count'] = row[4]
                inventory.append(enriched)
            return inventory
    except Exception as e:
        logger.error("Error fetching available inventory: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)

def assign_cable_to_order(serial_number, customer_gid, order_gid, line_item_skus):
    """Assign a cable to a customer order with SKU validation.

    Args:
        serial_number: Cable serial number
        customer_gid: Shopify customer GID
        order_gid: Shopify order GID
        line_item_skus: List of SKUs from order line items (for validation)

    Returns:
        dict with 'success' or 'error' key
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)

        from greenlight.cable_config import format_variant_sku

        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ac.serial_number, ac.sku_group, ac.length, ac.connector_code,
                           ac.shopify_gid, ac.shopify_order_gid
                    FROM audio_cables ac
                    WHERE ac.serial_number = %s
                """, (formatted_serial,))
                row = cur.fetchone()

                if not row:
                    return {
                        'error': 'not_found',
                        'message': f'Cable with serial number {formatted_serial} not found in database'
                    }

                (cable_serial, sku_group, length, connector_code,
                 existing_customer_gid, existing_order_gid) = row

                if existing_order_gid == order_gid:
                    return {
                        'error': 'duplicate',
                        'message': f'Cable {formatted_serial} is already scanned for this order'
                    }

                if existing_order_gid and existing_order_gid != order_gid:
                    return {
                        'error': 'already_assigned_order',
                        'message': f'Cable {formatted_serial} is assigned to a different order',
                        'existing_order_gid': existing_order_gid
                    }

                if existing_customer_gid and not existing_order_gid:
                    return {
                        'error': 'assigned_no_order',
                        'message': f'Cable {formatted_serial} is assigned to a customer without an order',
                        'existing_customer_gid': existing_customer_gid
                    }

                # SKU validation: compute the user-facing variant SKU from
                # (sku_group, length, connector_code) and match against the
                # order's line items (which carry variant SKU strings).
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, length=length_val, connector_code=connector_code,
                )
                if variant_sku not in line_item_skus:
                    return {
                        'error': 'sku_mismatch',
                        'message': f'Cable SKU {variant_sku} does not match any line item in this order',
                        'cable_sku': variant_sku,
                    }

                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = %s,
                        shopify_order_gid = %s,
                        updated_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s
                    RETURNING serial_number, sku_group
                """, (customer_gid, order_gid, formatted_serial))
                result = cur.fetchone()
                conn.commit()

                return {
                    'success': True,
                    'serial_number': result[0],
                    'sku_group': result[1],
                    'sku': variant_sku,  # backward-compat for callers expecting variant SKU here
                }
    except Exception as e:
        logger.error("Error assigning cable to order: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def force_assign_cable_to_order(serial_number, customer_gid, order_gid):
    """Override existing customer-only assignment and assign cable to an order.

    Used when operator confirms overriding an 'assigned_no_order' cable.
    Skips SKU validation (already validated before the confirmation prompt).
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = %s,
                        shopify_order_gid = %s,
                        updated_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s
                    RETURNING serial_number, sku_group
                """, (customer_gid, order_gid, formatted_serial))
                result = cur.fetchone()
                conn.commit()
                if result:
                    return {'success': True, 'serial_number': result[0], 'sku_group': result[1]}
                return {'error': 'not_found', 'message': f'Cable {formatted_serial} not found'}
    except Exception as e:
        logger.error("Error force-assigning cable to order: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def get_cables_for_order(order_gid):
    """Get all cables assigned to a specific order.

    Returns list of dicts with cable info for progress tracking.
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.length, ac.connector_code,
                       sg.description
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.shopify_order_gid = %s
                ORDER BY ac.updated_timestamp DESC
            """, (order_gid,))
            rows = cur.fetchall()
            return [
                _enrich_record({
                    'serial_number': r[0], 'sku_group': r[1],
                    'length': r[2], 'connector_code': r[3],
                    'description': r[4],
                })
                for r in rows
            ]
    except Exception as e:
        logger.error("Error fetching cables for order: %s", e)
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


def get_sku_stock_summary():
    """Get per-variant cable counts from Postgres.

    Phase 4: groups by (sku_group, length, connector_code) since each
    distinct variant is a separate "stock unit". Returns dict keyed by the
    user-facing variant SKU (computed via format_variant_sku) → counts.
    Excludes MISC variants from this summary (use get_misc_summary).
    """
    from greenlight.cable_config import format_variant_sku

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ac.sku_group, ac.length, ac.connector_code,
                    COUNT(*) as total,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed = TRUE
                        AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                    ) as available,
                    COUNT(*) FILTER (
                        WHERE ac.shopify_gid IS NOT NULL AND ac.shopify_gid != ''
                    ) as sold,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed = FALSE
                    ) as failed,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed IS NULL
                    ) as untested
                FROM audio_cables ac
                WHERE ac.sku_group !~ '-MISC-[0-9]+$'
                GROUP BY ac.sku_group, ac.length, ac.connector_code
                ORDER BY ac.sku_group, ac.length, ac.connector_code
            """)
            counts = {}
            for row in cur.fetchall():
                sku_group, length, connector_code, total, available, sold, failed, untested = row
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, length=length_val, connector_code=connector_code,
                )
                if variant_sku is None:
                    continue
                counts[variant_sku] = {
                    'total': total,
                    'available': available,
                    'sold': sold,
                    'failed': failed,
                    'untested': untested,
                }
            return counts
    except Exception as e:
        logger.error("Error fetching SKU stock summary: %s", e)
        return {}
    finally:
        pg_pool.putconn(conn)


def get_recent_sales(days=90):
    """Get cables sold (assigned to customer) in the last N days, grouped by variant.

    Returns dict: variant_sku -> count. Excludes MISC variants.
    """
    from greenlight.cable_config import format_variant_sku

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.sku_group, ac.length, ac.connector_code, COUNT(*)
                FROM audio_cables ac
                WHERE ac.shopify_gid IS NOT NULL AND ac.shopify_gid != ''
                  AND ac.updated_timestamp >= NOW() - INTERVAL '%s days'
                  AND ac.sku_group !~ '-MISC-[0-9]+$'
                GROUP BY ac.sku_group, ac.length, ac.connector_code
                ORDER BY COUNT(*) DESC
            """, (days,))
            sales = {}
            for sku_group, length, connector_code, count in cur.fetchall():
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, length=length_val, connector_code=connector_code,
                )
                if variant_sku:
                    sales[variant_sku] = count
            return sales
    except Exception as e:
        logger.error("Error fetching recent sales: %s", e)
        return {}
    finally:
        pg_pool.putconn(conn)


def get_misc_summary():
    """Get summary of MISC cables grouped by series.

    Returns dict: series_name -> {total, available, sold}.
    """
    from greenlight.cable_config import series_for_prefix

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    SUBSTRING(ac.sku_group FROM '^([A-Z]{2,3})') AS prefix,
                    COUNT(*) as total,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed = TRUE
                        AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                    ) as available,
                    COUNT(*) FILTER (
                        WHERE ac.shopify_gid IS NOT NULL AND ac.shopify_gid != ''
                    ) as sold
                FROM audio_cables ac
                WHERE ac.sku_group ~ '-MISC-[0-9]+$'
                GROUP BY prefix
            """)
            result = {}
            for prefix, total, available, sold in cur.fetchall():
                series_name = series_for_prefix(prefix) or prefix
                result[series_name] = {"total": total, "available": available, "sold": sold}
            return result
    except Exception as e:
        logger.error("Error fetching MISC summary: %s", e)
        return {}
    finally:
        pg_pool.putconn(conn)


def get_available_series():
    """Get list of product series that have available inventory.

    Returns series names sorted alphabetically. Derives series from SKU prefix
    via the YAML resolver — the cable_skus.series column goes away in 3.5.
    """
    from greenlight.cable_config import series_for_prefix

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT SUBSTRING(ac.sku_group FROM '^([A-Z]{2,3})') AS prefix
                FROM audio_cables ac
                WHERE ac.shopify_gid IS NULL OR ac.shopify_gid = ''
            """)
            prefixes = [r[0] for r in cur.fetchall() if r[0]]
            series_names = [series_for_prefix(p) for p in prefixes]
            return sorted([s for s in series_names if s])
    except Exception as e:
        logger.error("Error fetching available series: %s", e)
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
