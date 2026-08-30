import logging
import re

import psycopg2
from psycopg2.extras import Json
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
            cur.execute("SELECT nextval('audio_cable_serial_seq')")
            serial_num = cur.fetchone()[0]
            return f"SD{serial_num:06d}"
    except Exception as e:
        logger.error("Error generating serial number: %s", e)
        return None
    finally:
        pg_pool.putconn(conn)

# The operator chosen at login. Greenlight runs one operator per session, so
# threading an actor through every mutation signature would be noise — screens
# set this once and cable events attribute themselves.
_current_operator = None


def set_current_operator(operator_code):
    """Record who is driving this session, for cable_events attribution."""
    global _current_operator
    _current_operator = operator_code


def record_cable_event(serial_number, event, detail=None, actor=None, cur=None):
    """Append an immutable audit row for a change to a cable.

    Every commercial mutation overwrites in place, so without this there is no
    way to answer "who cleared this registration code?" or to notice that an
    assignment quietly destroyed dealer attribution.

    Args:
        serial_number: Cable serial number
        event: Event slug — see EVENT_* constants below. Free text rather than
            an enum so Greenlight and the Shopify app can add events without
            coordinating a migration.
        detail: JSON-serializable dict, conventionally {'from': ..., 'to': ...}
        actor: Overrides the session operator. The admin app writes
            'admin:<staff email>' so the two sources stay distinguishable.
        cur: An open cursor to write through, so the event commits atomically
            with the mutation it describes. Wrapped in a SAVEPOINT: a failed
            audit write must not abort the caller's transaction, and an event
            must never outlive a mutation that rolled back.

    Never raises — a failed audit write is logged, not propagated.
    """
    payload = Json(detail) if detail is not None else None
    who = actor if actor is not None else _current_operator

    if cur is not None:
        try:
            cur.execute("SAVEPOINT cable_event")
            cur.execute("""
                INSERT INTO cable_events (serial_number, event, actor, detail)
                VALUES (%s, %s, %s, %s)
            """, (serial_number, event, who, payload))
            cur.execute("RELEASE SAVEPOINT cable_event")
        except Exception as e:
            logger.error("Failed to record cable event %s for %s: %s", event, serial_number, e)
            try:
                cur.execute("ROLLBACK TO SAVEPOINT cable_event")
            except Exception:
                pass
        return

    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as own:
                own.execute("""
                    INSERT INTO cable_events (serial_number, event, actor, detail)
                    VALUES (%s, %s, %s, %s)
                """, (serial_number, event, who, payload))
            conn.commit()
    except Exception as e:
        logger.error("Failed to record cable event %s for %s: %s", event, serial_number, e)
        conn.rollback()
    finally:
        pg_pool.putconn(conn)


def get_cable_events(serial_number, limit=50):
    """Most-recent-first audit history for one cable."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT event, actor, detail, created_at
                FROM cable_events
                WHERE serial_number = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
            """, (format_serial_number(serial_number), limit))
            return [
                {'event': r[0], 'actor': r[1], 'detail': r[2], 'created_at': r[3]}
                for r in cur.fetchall()
            ]
    except Exception as e:
        logger.error("Error fetching cable events: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def get_audio_cable(serial_number):
    """Get audio cable record by serial number."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.prefix,
                       ac.length, ac.connector_code, ac.connector_finish,
                       ac.resistance_adc, ac.calibration_adc,
                       ac.resistance_adc_p3, ac.calibration_adc_p3, ac.test_passed,
                       ac.operator, ac.arduino_unit_id, ac.notes, ac.test_timestamp,
                       ac.shopify_gid, ac.updated_timestamp,
                       sg.description, sg.archived_at,
                       ac.registration_code,
                       ac.wholesale_company_gid, ac.wholesale_location_gid,
                       ac.registered_at
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
    match = re.match(r'^([A-Za-z]*)(\d+)$', serial_number)
    if match:
        prefix = match.group(1)
        number = match.group(2)
        padded_number = number.zfill(6)
        return f"{prefix}{padded_number}"
    return serial_number

def register_scanned_cable(serial_number, sku_group, prefix, length, connector_code,
                           operator=None, update_if_exists=False, connector_finish=None):
    """Register a cable with a scanned serial number (Phase 5 intake workflow).

    Args:
        serial_number: The serial number from the cable label
        sku_group: The sku_group identifier. Phase 5 group SKU shapes:
            'GL' (catalog pattern code), 'LTD-PHISH26' (series-agnostic LTD),
            'SC-MISC-42' (still series-scoped).
        prefix: Series prefix (e.g. 'SC', 'TC'). Required — lives on
            audio_cables.prefix so the per-cable variant SKU can be derived
            even for catalog/LTD groups whose group SKU drops the prefix.
            For MISC the prefix matches the one inside the group SKU; we
            still store it explicitly for query simplicity.
        length: Cable length in feet (numeric)
        connector_code: Connector code per the YAML connectors[] list —
            '' for straight, '-R' for right angle (catalog cables); MISC/LTD
            cables also carry a connector_code on audio_cables.
        operator: Operator ID who registered the cable
        update_if_exists: If True, update existing cable records
    """
    if length is None:
        return {'error': 'invalid_length', 'message': 'length is required'}
    if not prefix:
        return {'error': 'invalid_prefix', 'message': 'prefix is required'}
    if connector_code is None:
        connector_code = ''

    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)

        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT serial_number, sku_group, prefix, length, connector_code,
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
                                'prefix': existing[2],
                                'length': float(existing[3]) if existing[3] is not None else None,
                                'connector_code': existing[4],
                                'operator': existing[5],
                                'timestamp': existing[6],
                                'notes': existing[7],
                            }
                        }
                    cur.execute("""
                        UPDATE audio_cables
                        SET sku_group = %s,
                            prefix = %s,
                            length = %s,
                            connector_code = %s,
                            connector_finish = %s,
                            operator = %s,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number, updated_timestamp
                    """, (sku_group, prefix, length, connector_code, connector_finish,
                          operator, formatted_serial))
                    result = cur.fetchone()
                    record_cable_event(
                        formatted_serial, 'sku_changed',
                        detail={
                            'from': {'sku_group': existing[1], 'prefix': existing[2],
                                     'length': float(existing[3]) if existing[3] is not None else None,
                                     'connector_code': existing[4]},
                            'to': {'sku_group': sku_group, 'prefix': prefix,
                                   'length': float(length), 'connector_code': connector_code},
                        },
                        actor=operator, cur=cur,
                    )
                    conn.commit()
                    return {
                        'serial_number': result[0],
                        'timestamp': result[1],
                        'sku_group': sku_group,
                        'prefix': prefix,
                        'length': float(length),
                        'connector_code': connector_code,
                        'success': True,
                        'updated': True,
                    }

                cur.execute("""
                    INSERT INTO audio_cables
                        (serial_number, sku_group, prefix, length, connector_code,
                         connector_finish, resistance_adc, operator, arduino_unit_id, notes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING serial_number, updated_timestamp
                """, (formatted_serial, sku_group, prefix, length, connector_code,
                      connector_finish, None, operator, None, 'Scanned intake'))
                result = cur.fetchone()
                conn.commit()
                return {
                    'serial_number': result[0],
                    'timestamp': result[1],
                    'sku_group': sku_group,
                    'prefix': prefix,
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
                if result:
                    record_cable_event(serial_number, 'qc_tested',
                                       detail={'to': 'pass' if test_passed else 'fail',
                                               'resistance_adc': resistance_adc},
                                       actor=operator, cur=cur)
                conn.commit()
                return result[0] if result else None
    except Exception as e:
        logger.error("Error updating cable test results: %s", e)
        conn.rollback()
        return None
    finally:
        pg_pool.putconn(conn)


def sku_kind(sku):
    """Classify a SKU (variant or group) by pattern.

    Tries variant SKU first ('SC-12GL', 'SC-12GL-R', 'SC-12-LTD-PHISH26-R'),
    then group SKU ('GL', 'LTD-PHISH26', 'SC-MISC-42'). Returns 'catalog',
    'misc', or 'ltd'. Unrecognized inputs default to 'catalog'.
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
    """Add resolver-derived fields to a cable record dict (Phase 5).

    Required keys: 'sku_group'. The 'prefix' lives on audio_cables in
    Phase 5 — supply it on the record dict (the SELECT helpers below all
    pull `ac.prefix`). Optional: 'length', 'connector_code', 'description',
    'archived_at'. Mutates record in place and returns it.

    Populates from the resolver:
      - kind, series
      - pattern_code, pattern_name (catalog only; None for MISC/LTD)
      - connector_display (looked up from prefix + connector_code)
      - core_cable, braid_material (series-level from YAML)
      - variant_sku — the user-facing SKU string Shopify uses
      - slug (LTD only)

    """
    from greenlight.cable_config import (
        parse_group_sku, format_variant_sku, series_data_for_prefix,
        connector_display_for, series_for_prefix, finish_display,
    )
    sku_group = record.get('sku_group')
    parsed = parse_group_sku(sku_group)
    kind = parsed.get('kind')

    # Phase 5: prefix lives on audio_cables. For MISC the prefix is also
    # encoded in the group SKU so prefer the column but fall back if missing
    # (e.g. record built outside the DB layer).
    prefix = record.get('prefix') or parsed.get('prefix')
    record['prefix'] = prefix

    record['kind'] = kind
    record['series'] = series_for_prefix(prefix) if prefix else None

    if kind == 'catalog':
        record['pattern_code'] = parsed.get('pattern_code')
        record['pattern_name'] = parsed.get('pattern_name')
    else:
        record['pattern_code'] = None
        record['pattern_name'] = None

    if kind == 'ltd':
        record['slug'] = parsed.get('slug')

    # Length lives on audio_cables.length now (NUMERIC(5,2) → Decimal).
    # Coerce to float so consumers see a stable type.
    raw_length = record.get('length')
    if raw_length is not None:
        try:
            record['length'] = float(raw_length)
        except (TypeError, ValueError):
            pass

    connector_code = record.get('connector_code') or ''
    record['connector_code'] = connector_code
    record['connector_display'] = (
        connector_display_for(prefix, connector_code) if prefix else None
    )

    # Connector finish (custom/LTD only; None for standard catalog cables).
    record['connector_finish_display'] = finish_display(record.get('connector_finish'))

    series_data = series_data_for_prefix(prefix) if prefix else None
    if series_data:
        record['core_cable'] = series_data.get('core_cable')
        record['braid_material'] = series_data.get('braid_material')
    else:
        record['core_cable'] = None
        record['braid_material'] = None

    # User-facing variant SKU. Phase 5: prefix kwarg is required for catalog
    # and LTD (whose group SKU dropped the prefix); MISC ignores it.
    record['variant_sku'] = format_variant_sku(
        group_sku=sku_group,
        prefix=prefix,
        length=record.get('length'),
        connector_code=connector_code,
    )

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


def get_or_create_misc_sku(series_prefix, description, length):
    """Look up or create a MISC sku_group.

    Dedupes by (series_prefix, description, length-of-cables-in-group):
    each MISC sku_group holds cables of a single length. If an existing
    group has matching description and at least one cable already of the
    requested length, reuse it; otherwise create a new group.

    The length is matched against existing cables (audio_cables.length),
    not stored on sku_group itself — Phase 4 keeps length per-cable on
    audio_cables. This means a freshly-created group with no cables yet
    is NOT considered a match (small orphan-group risk if a session is
    abandoned mid-flow; acceptable, can be pruned).

    Args:
        series_prefix: e.g. "SC", "TC"
        description: Free-form group description
        length: Cable length in feet (numeric); part of dedup key

    Returns:
        sku string, or None on error
    """
    from greenlight.cable_config import series_for_prefix

    if series_for_prefix(series_prefix) is None:
        logger.error("Unknown series prefix %s — no YAML config", series_prefix)
        return None
    if length is None:
        logger.error("get_or_create_misc_sku called without length")
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
                    SELECT sg.sku
                    FROM sku_group sg
                    WHERE sg.sku LIKE %s
                      AND sg.description = %s
                      AND EXISTS (
                          SELECT 1 FROM audio_cables ac
                          WHERE ac.sku_group = sg.sku
                            AND ac.length = %s
                      )
                    ORDER BY sg.sku
                    LIMIT 1
                """, (f"{series_prefix}-MISC-%", description, length))
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


def search_misc_variants(series_prefix):
    """Return recent MISC groups for a series prefix (for picker UI).

    Each MISC group holds cables of a single length post-Phase-4-rev2; the
    `length` field returned here is that length (NULL for freshly-created
    groups with no cables yet, which the picker can hide or label as
    "empty").

    Args:
        series_prefix: e.g. "SC", "TC"

    Returns:
        List of dicts with sku, description, length, cable_count
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT sg.sku, sg.description,
                       (SELECT MIN(ac.length) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS length,
                       (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
                FROM sku_group sg
                WHERE sg.sku LIKE %s
                  AND sg.sku ~ '-MISC-[0-9]+$'
                ORDER BY sg.sku DESC
                LIMIT 20
            """, (f"{series_prefix}-MISC-%",))
            rows = cur.fetchall()
            return [
                {
                    'sku': r[0],
                    'description': r[1],
                    'length': float(r[2]) if r[2] is not None else None,
                    'cable_count': r[3],
                }
                for r in rows
            ]
    except Exception as e:
        logger.error("Error searching MISC groups: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def list_ltd_editions(active_only=True):
    """List LTD editions with cable counts (read-only; CRUD lives in shopify_app).

    Phase 5: LTD groups are series-agnostic ('LTD-PHISH26'); any series prefix
    can be attached at per-cable registration time.

    Args:
        active_only: If True, exclude archived editions

    Returns:
        List of dicts with sku, slug, description, archived_at, active, cable_count.
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            where_clauses = ["sg.sku ~ '^LTD-[A-Z0-9]{4,24}$'"]
            if active_only:
                where_clauses.append("sg.archived_at IS NULL")

            where_sql = " AND ".join(where_clauses)
            cur.execute(f"""
                SELECT sg.sku, sg.description, sg.archived_at,
                       (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
                FROM sku_group sg
                WHERE {where_sql}
                ORDER BY (sg.archived_at IS NULL) DESC, sg.sku
            """)
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    'sku_group': r[0],
                    'sku': r[0],
                    'slug': r[0].split('-', 1)[1],
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
    cable_count — or None.
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
                'slug': row[0].split('-', 1)[1],
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


def get_cables_for_ltd_sku(ltd_group_sku):
    """Get every cable registered under an LTD group SKU, assigned or not.

    Unlike get_cables_for_customer, this returns all states: each record
    carries shopify_gid (the end owner, or None/'' if unclaimed),
    wholesale_company_gid (the dealer, if sold through one) and test_passed,
    so callers can show both channels and QC status. A dealer-sold cable has
    no shopify_gid until its buyer registers, so showing only shopify_gid
    would report it as unassigned.

    Args:
        ltd_group_sku: LTD group SKU, e.g. 'LTD-PHISH26'

    Returns:
        List of enriched cable dicts ordered by serial number.
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.prefix,
                       ac.length, ac.connector_code, ac.connector_finish,
                       ac.updated_timestamp, ac.shopify_gid, ac.test_passed,
                       sg.description, sg.archived_at,
                       ac.wholesale_company_gid, ac.registered_at
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.sku_group = %s
                ORDER BY ac.serial_number
            """, (ltd_group_sku,))
            rows = cur.fetchall()

            cables = []
            for row in rows:
                cables.append(_enrich_record({
                    'serial_number': row[0],
                    'sku_group': row[1],
                    'prefix': row[2],
                    'length': row[3],
                    'connector_code': row[4],
                    'connector_finish': row[5],
                    'updated_timestamp': row[6],
                    'shopify_gid': row[7],
                    'test_passed': row[8],
                    'description': row[9],
                    'archived_at': row[10],
                    'wholesale_company_gid': row[11],
                    'registered_at': row[12],
                }))
            return cables
    except Exception as e:
        logger.error("Error fetching cables for LTD sku %s: %s", ltd_group_sku, e)
        return []
    finally:
        pg_pool.putconn(conn)


def get_available_count_for_sku(sku):
    """Get count of available cables for a SKU.

    "Available" means passed QC, not sold to a customer, and not sold to a
    wholesale dealer.

    A registration_code does NOT affect availability. Codes are printed for
    cables we expect an end buyer to register — including batches we take to a
    festival to sell direct — and those cables remain ours and sellable through
    either channel until one actually sells. Only wholesale_company_gid (sold to
    a dealer) or shopify_gid (sold to a customer) takes a cable out of stock.

    Note these counts are largely for internal reporting: the storefront is set
    to continue selling when out of stock and standard SKUs are built to order.
    The real safeguard is the QC and ownership gate at allocation time.

    The input may be either a variant SKU (e.g. 'SC-12GL', 'SC-12GL-R',
    'SC-12-LTD-PHISH26-R') or a group/MISC/LTD SKU. Catalog and LTD variants
    are fully qualified — split into (sku_group, prefix, length,
    connector_code) for the count. Bare group/MISC inputs match all cables
    in that group regardless of length/connector.
    """
    from greenlight.cable_config import parse_variant_sku

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            parsed = parse_variant_sku(sku)
            kind = parsed.get('kind')
            if kind in ('catalog', 'ltd'):
                cur.execute("""
                    SELECT COUNT(*)
                    FROM audio_cables ac
                    WHERE ac.test_passed = TRUE
                      AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                      AND ac.wholesale_company_gid IS NULL
                      AND ac.sku_group = %s
                      AND ac.prefix = %s
                      AND ac.length = %s
                      AND ac.connector_code = %s
                """, (parsed['group_sku'], parsed['prefix'], parsed['length'],
                      parsed.get('connector_code') or ''))
            else:
                # MISC variant SKU == group SKU; or caller passed a bare group SKU
                cur.execute("""
                    SELECT COUNT(*)
                    FROM audio_cables ac
                    WHERE ac.test_passed = TRUE
                      AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                      AND ac.wholesale_company_gid IS NULL
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
        formatted_serial = format_serial_number(serial_number)

        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT serial_number, sku_group, shopify_gid, wholesale_company_gid,
                           test_passed
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

                if existing[4] is not True:
                    return {
                        'error': 'qc_failed' if existing[4] is False else 'not_tested',
                        'message': (f'Cable {formatted_serial} failed QC and cannot be assigned'
                                    if existing[4] is False else
                                    f'Cable {formatted_serial} has not passed QC yet'),
                    }

                if existing[3]:
                    # Sold to a dealer. shopify_gid is NULL by design there — it
                    # is reserved for the end buyer who registers the cable — so
                    # the check above does not catch this. Handing it to a retail
                    # customer as well would sell the same cable twice.
                    return {
                        'error': 'sold_to_dealer',
                        'message': (f'Cable {formatted_serial} has been sold to a dealer and '
                                    f'cannot be assigned to a retail customer'),
                        'wholesale_company_gid': existing[3],
                    }

                cur.execute("""
                    UPDATE audio_cables
                    SET shopify_gid = %s
                    WHERE serial_number = %s
                    RETURNING serial_number, sku_group, shopify_gid
                """, (customer_shopify_gid, formatted_serial))
                result = cur.fetchone()
                record_cable_event(formatted_serial, 'assigned_customer',
                                   detail={'to': customer_shopify_gid}, cur=cur)
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


def unassign_cable(serial_number, channel=None):
    """Release a cable from one commercial channel, returning it to inventory.

    A cable can be committed to both channels at once: sold to a dealer
    (wholesale_company_gid) and later registered by the end buyer who bought it
    from that dealer (shopify_gid). Clearing both together would destroy the
    dealer attribution this feature exists to preserve, so the channel is
    explicit whenever it is ambiguous.

    Args:
        serial_number: Cable serial number
        channel: 'retail' (release the end owner), 'wholesale' (release the
            dealer), or None to infer when only one channel is set. None on a
            cable committed to both is an error rather than a guess.

    Returns:
        dict with 'success' and 'channel', or 'error'/'message'
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT shopify_gid, wholesale_company_gid
                    FROM audio_cables WHERE serial_number = %s
                """, (formatted_serial,))
                prior = cur.fetchone()
                if not prior:
                    return {'error': 'not_found', 'message': f'Cable {formatted_serial} not found'}

                prior_customer, prior_company = prior
                if not prior_customer and not prior_company:
                    return {
                        'error': 'not_assigned',
                        'message': f'Cable {formatted_serial} is not assigned to anyone'
                    }

                if channel is None:
                    if prior_customer and prior_company:
                        return {
                            'error': 'ambiguous_channel',
                            'message': (f'Cable {formatted_serial} is both sold to a dealer and '
                                        f'registered to an owner — specify which to release'),
                        }
                    channel = 'retail' if prior_customer else 'wholesale'

                if channel not in ('retail', 'wholesale'):
                    return {'error': 'bad_channel', 'message': f'Unknown channel {channel!r}'}

                if channel == 'retail':
                    if not prior_customer:
                        return {
                            'error': 'not_assigned',
                            'message': f'Cable {formatted_serial} has no registered owner'
                        }
                    # The order gid belongs to whichever channel bought the cable.
                    # On a dealer-sold cable it's the B2B order, so releasing the
                    # end owner must leave it intact.
                    cur.execute("""
                        UPDATE audio_cables
                        SET shopify_gid = NULL,
                            registered_at = NULL,
                            shopify_order_gid = CASE WHEN wholesale_company_gid IS NULL
                                                     THEN NULL ELSE shopify_order_gid END,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number
                    """, (formatted_serial,))
                else:
                    if not prior_company:
                        return {
                            'error': 'not_assigned',
                            'message': f'Cable {formatted_serial} is not sold to a dealer'
                        }
                    cur.execute("""
                        UPDATE audio_cables
                        SET wholesale_company_gid = NULL,
                            wholesale_location_gid = NULL,
                            shopify_order_gid = NULL,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number
                    """, (formatted_serial,))

                result = cur.fetchone()
                record_cable_event(
                    formatted_serial,
                    'unassigned_customer' if channel == 'retail' else 'unassigned_dealer',
                    detail={'from': prior_customer if channel == 'retail' else prior_company},
                    cur=cur,
                )
                conn.commit()
                return {'success': True, 'serial_number': result[0], 'channel': channel}
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
                if result:
                    record_cable_event(formatted_serial, 'assigned_customer',
                                       detail={'to': customer_shopify_gid, 'forced': True}, cur=cur)
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
                SELECT ac.serial_number, ac.sku_group, ac.prefix,
                       ac.length, ac.connector_code,
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
                    'prefix': row[2],
                    'length': row[3],
                    'connector_code': row[4],
                    'updated_timestamp': row[5],
                    'description': row[6],
                    'archived_at': row[7],
                }))
            return cables
    except Exception as e:
        logger.error("Error fetching cables for customer: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def get_cables_for_company(company_gid):
    """Get all cables sold to a wholesale dealer (B2B company).

    The wholesale counterpart to get_cables_for_customer. Because a B2B sale
    leaves shopify_gid NULL for the end buyer to claim, dealer cables never show
    up in the customer query and need their own lookup.

    registered_at tells you which of the dealer's cables have reached an end
    buyer — NULL means it's still on their shelf (or was never registered).
    """
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.prefix,
                       ac.length, ac.connector_code,
                       ac.updated_timestamp, sg.description, sg.archived_at,
                       ac.wholesale_location_gid, ac.registration_code,
                       ac.registered_at, ac.shopify_gid
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.wholesale_company_gid = %s
                ORDER BY ac.updated_timestamp DESC
            """, (company_gid,))
            return [
                _enrich_record({
                    'serial_number': row[0],
                    'sku_group': row[1],
                    'prefix': row[2],
                    'length': row[3],
                    'connector_code': row[4],
                    'updated_timestamp': row[5],
                    'description': row[6],
                    'archived_at': row[7],
                    'wholesale_location_gid': row[8],
                    'registration_code': row[9],
                    'registered_at': row[10],
                    'shopify_gid': row[11],
                })
                for row in cur.fetchall()
            ]
    except Exception as e:
        logger.error("Error fetching cables for company: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def get_all_cables(limit=100, offset=0):
    """Get all cables ordered by serial number descending (highest first)"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ac.serial_number, ac.sku_group, ac.prefix,
                       ac.length, ac.connector_code,
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
                    'prefix': row[2],
                    'length': row[3],
                    'connector_code': row[4],
                    'updated_timestamp': row[5],
                    'test_timestamp': row[6],
                    'resistance_adc': row[7],
                    'test_passed': row[8],
                    'operator': row[9],
                    'shopify_gid': row[10],
                    'description': row[11],
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

    Phase 5: rolls up by (sku_group, prefix, length, connector_code) since the
    same sku_group can hold cables of multiple prefixes (LTD), lengths, and
    connectors. Each row in the result represents a distinct variant the
    operator can fulfill from.

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
                    ac.prefix,
                    ac.length,
                    ac.connector_code,
                    sg.description,
                    COUNT(*) as available_count
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.test_passed = TRUE
                  AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                  AND ac.wholesale_company_gid IS NULL
            """
            params = []
            if series:
                prefix = prefix_for_series(series)
                if prefix is None:
                    return []
                query += " AND ac.prefix = %s"
                params.append(prefix)
            query += """
                GROUP BY ac.sku_group, ac.prefix, ac.length, ac.connector_code, sg.description
                ORDER BY ac.prefix, ac.sku_group, ac.length, ac.connector_code
            """
            cur.execute(query, params)
            rows = cur.fetchall()

            inventory = []
            for row in rows:
                enriched = _enrich_record({
                    'sku_group': row[0],
                    'prefix': row[1],
                    'length': row[2],
                    'connector_code': row[3],
                    'description': row[4],
                })
                enriched['available_count'] = row[5]
                inventory.append(enriched)
            return inventory
    except Exception as e:
        logger.error("Error fetching available inventory: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)

def assign_cable_to_order(serial_number, customer_gid, order_gid, line_item_skus,
                          company_gid=None, location_gid=None):
    """Assign a cable to an order with SKU validation.

    Two channels, decided by whether the order is B2B:

      retail    (company_gid None) -> shopify_gid = customer_gid
      wholesale (company_gid set)  -> wholesale_company_gid / wholesale_location_gid,
                                      and shopify_gid is left NULL so the end buyer
                                      can still claim the cable with its
                                      registration code

    Shopify surfaces the distinction as Order.purchasingEntity: a retail order
    resolves to Customer, a B2B order to PurchasingCompany (company + location).

    Args:
        serial_number: Cable serial number
        customer_gid: Shopify customer GID (retail; ignored when company_gid is set)
        order_gid: Shopify order GID
        line_item_skus: List of SKUs from order line items (for validation)
        company_gid: Shopify Company GID for a B2B order
        location_gid: Shopify CompanyLocation GID for a B2B order

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
                    SELECT ac.serial_number, ac.sku_group, ac.prefix,
                           ac.length, ac.connector_code,
                           ac.shopify_gid, ac.shopify_order_gid,
                           ac.wholesale_company_gid, ac.test_passed
                    FROM audio_cables ac
                    WHERE ac.serial_number = %s
                """, (formatted_serial,))
                row = cur.fetchone()

                if not row:
                    return {
                        'error': 'not_found',
                        'message': f'Cable with serial number {formatted_serial} not found in database'
                    }

                (cable_serial, sku_group, prefix, length, connector_code,
                 existing_customer_gid, existing_order_gid,
                 existing_company_gid, test_passed) = row

                # A cable goes out to a customer only once it has passed QC.
                # Inventory counts don't gate this — the store sells when out of
                # stock and we build to order — so allocation is the only place
                # an untested or failed cable can be caught before it ships.
                if test_passed is not True:
                    return {
                        'error': 'qc_failed' if test_passed is False else 'not_tested',
                        'message': (f'Cable {formatted_serial} failed QC and cannot be allocated'
                                    if test_passed is False else
                                    f'Cable {formatted_serial} has not passed QC yet'),
                    }

                if not company_gid and existing_company_gid:
                    return {
                        'error': 'sold_to_dealer',
                        'message': (f'Cable {formatted_serial} is sold to a dealer and cannot '
                                    f'be allocated to a retail order'),
                    }

                if company_gid and existing_customer_gid:
                    # shopify_gid means end owner, so this cable has already been
                    # registered by a buyer — it can't now be sold to a dealer.
                    return {
                        'error': 'already_registered',
                        'message': f'Cable {formatted_serial} is registered to an end owner '
                                   f'and cannot be assigned to a dealer'
                    }

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
                # (sku_group, prefix, length, connector_code) and match against
                # the order's line items (which carry variant SKU strings).
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, prefix=prefix,
                    length=length_val, connector_code=connector_code,
                )
                if variant_sku not in line_item_skus:
                    return {
                        'error': 'sku_mismatch',
                        'message': f'Cable SKU {variant_sku} does not match any line item in this order',
                        'cable_sku': variant_sku,
                    }

                if company_gid:
                    # Wholesale: record the dealer, leave shopify_gid for the
                    # end buyer's registration.
                    cur.execute("""
                        UPDATE audio_cables
                        SET wholesale_company_gid = %s,
                            wholesale_location_gid = %s,
                            shopify_order_gid = %s,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number, sku_group
                    """, (company_gid, location_gid, order_gid, formatted_serial))
                else:
                    cur.execute("""
                        UPDATE audio_cables
                        SET shopify_gid = %s,
                            shopify_order_gid = %s,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number, sku_group
                    """, (customer_gid, order_gid, formatted_serial))
                result = cur.fetchone()
                record_cable_event(
                    formatted_serial,
                    'assigned_dealer' if company_gid else 'assigned_customer',
                    detail={'to': company_gid or customer_gid, 'order': order_gid,
                            'location': location_gid} if company_gid
                           else {'to': customer_gid, 'order': order_gid},
                    cur=cur,
                )
                conn.commit()

                return {
                    'success': True,
                    'serial_number': result[0],
                    'sku_group': result[1],
                    'sku': variant_sku,
                    'channel': 'wholesale' if company_gid else 'retail',
                }
    except Exception as e:
        logger.error("Error assigning cable to order: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
    finally:
        pg_pool.putconn(conn)


def force_assign_cable_to_order(serial_number, customer_gid, order_gid,
                                company_gid=None, location_gid=None):
    """Override existing customer-only assignment and assign cable to an order.

    Used when operator confirms overriding an 'assigned_no_order' cable.
    Skips SKU validation (already validated before the confirmation prompt).

    Same retail/wholesale split as assign_cable_to_order: when company_gid is
    given the cable is recorded against the dealer and shopify_gid is cleared,
    since a forced wholesale assignment means the cable is going out to a store
    rather than to the customer it was previously held for.
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                if company_gid:
                    cur.execute("""
                        UPDATE audio_cables
                        SET wholesale_company_gid = %s,
                            wholesale_location_gid = %s,
                            shopify_order_gid = %s,
                            shopify_gid = NULL,
                            -- The prior owner is being dropped, so their
                            -- registration date must go with them.
                            registered_at = NULL,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number, sku_group
                    """, (company_gid, location_gid, order_gid, formatted_serial))
                else:
                    cur.execute("""
                        UPDATE audio_cables
                        SET shopify_gid = %s,
                            shopify_order_gid = %s,
                            updated_timestamp = CURRENT_TIMESTAMP
                        WHERE serial_number = %s
                        RETURNING serial_number, sku_group
                    """, (customer_gid, order_gid, formatted_serial))
                result = cur.fetchone()
                if result:
                    record_cable_event(
                        formatted_serial,
                        'assigned_dealer' if company_gid else 'assigned_customer',
                        detail={'to': company_gid or customer_gid, 'order': order_gid,
                                'forced': True},
                        cur=cur,
                    )
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
                SELECT ac.serial_number, ac.sku_group, ac.prefix,
                       ac.length, ac.connector_code,
                       sg.description
                FROM audio_cables ac
                JOIN sku_group sg ON ac.sku_group = sg.sku
                WHERE ac.shopify_order_gid = %s
                ORDER BY ac.updated_timestamp DESC
            """, (order_gid,))
            rows = cur.fetchall()
            return [
                _enrich_record({
                    'serial_number': r[0], 'sku_group': r[1], 'prefix': r[2],
                    'length': r[3], 'connector_code': r[4],
                    'description': r[5],
                })
                for r in rows
            ]
    except Exception as e:
        logger.error("Error fetching cables for order: %s", e)
        return []
    finally:
        pg_pool.putconn(conn)


def clear_registration_code(serial_number):
    """Detach a cable's registration code.

    This does not change availability: a code is not a state that removes a
    cable from stock (see get_available_count_for_sku). Use it to undo a
    mis-scan, or to reissue under a new code — noting that any label already
    printed with the old code stops working.

    Returns:
        dict with 'success' and the cleared code, or 'error'/'message'
    """
    conn = pg_pool.getconn()
    try:
        formatted_serial = format_serial_number(serial_number)
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE audio_cables
                    SET registration_code = NULL,
                        updated_timestamp = CURRENT_TIMESTAMP
                    WHERE serial_number = %s AND registration_code IS NOT NULL
                    RETURNING serial_number
                """, (formatted_serial,))
                result = cur.fetchone()
                if result:
                    record_cable_event(formatted_serial, 'code_cleared', cur=cur)
                conn.commit()
                if result:
                    return {'success': True, 'serial_number': result[0]}
                return {
                    'error': 'no_code',
                    'message': f'Cable {formatted_serial} has no registration code'
                }
    except Exception as e:
        logger.error("Error clearing registration code: %s", e)
        conn.rollback()
        return {'error': 'database', 'message': str(e)}
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
                                record_cable_event(result[0], 'code_generated',
                                                   detail={'to': result[1]}, cur=cur)
                                assigned = True
                                break
                            else:
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
                                assigned = True
                                break
                        except Exception as e:
                            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
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

    Phase 5: groups by (sku_group, prefix, length, connector_code) since each
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
                    ac.sku_group, ac.prefix, ac.length, ac.connector_code,
                    COUNT(*) as total,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed = TRUE
                        AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                        AND ac.wholesale_company_gid IS NULL
                    ) as available,
                    -- Sold through either channel. A dealer sale leaves
                    -- shopify_gid NULL for the end buyer, so counting only
                    -- shopify_gid would report a sold cable as still in stock.
                    COUNT(*) FILTER (
                        WHERE (ac.shopify_gid IS NOT NULL AND ac.shopify_gid != '')
                           OR ac.wholesale_company_gid IS NOT NULL
                    ) as sold,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed = FALSE
                    ) as failed,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed IS NULL
                    ) as untested
                FROM audio_cables ac
                WHERE ac.sku_group !~ '-MISC-[0-9]+$'
                GROUP BY ac.sku_group, ac.prefix, ac.length, ac.connector_code
                ORDER BY ac.prefix, ac.sku_group, ac.length, ac.connector_code
            """)
            counts = {}
            for row in cur.fetchall():
                sku_group, prefix, length, connector_code, total, available, sold, failed, untested = row
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, prefix=prefix,
                    length=length_val, connector_code=connector_code,
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
                SELECT ac.sku_group, ac.prefix, ac.length, ac.connector_code, COUNT(*)
                FROM audio_cables ac
                WHERE ac.shopify_gid IS NOT NULL AND ac.shopify_gid != ''
                  AND ac.updated_timestamp >= NOW() - INTERVAL '%s days'
                  AND ac.sku_group !~ '-MISC-[0-9]+$'
                GROUP BY ac.sku_group, ac.prefix, ac.length, ac.connector_code
                ORDER BY COUNT(*) DESC
            """, (days,))
            sales = {}
            for sku_group, prefix, length, connector_code, count in cur.fetchall():
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, prefix=prefix,
                    length=length_val, connector_code=connector_code,
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
                    ac.prefix,
                    COUNT(*) as total,
                    COUNT(*) FILTER (
                        WHERE ac.test_passed = TRUE
                        AND (ac.shopify_gid IS NULL OR ac.shopify_gid = '')
                        AND ac.wholesale_company_gid IS NULL
                    ) as available,
                    -- Sold through either channel. A dealer sale leaves
                    -- shopify_gid NULL for the end buyer, so counting only
                    -- shopify_gid would report a sold cable as still in stock.
                    COUNT(*) FILTER (
                        WHERE (ac.shopify_gid IS NOT NULL AND ac.shopify_gid != '')
                           OR ac.wholesale_company_gid IS NOT NULL
                    ) as sold
                FROM audio_cables ac
                WHERE ac.sku_group ~ '-MISC-[0-9]+$'
                GROUP BY ac.prefix
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

    Returns series names sorted alphabetically. Derives series from
    audio_cables.prefix via the YAML resolver.
    """
    from greenlight.cable_config import series_for_prefix

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ac.prefix
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
