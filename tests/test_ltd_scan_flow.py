#!/usr/bin/env python3
"""Test LTD scan flow: insert an LTD edition (cable_skus + cable_ltd_metadata),
register a cable, verify get_audio_cable surfaces event_name, and confirm
sku_kind / list_ltd_editions work as expected.

This script directly writes to cable_ltd_metadata to simulate what the
Shopify app's CRUD UI will do — useful before that UI is built.
"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import (
    register_scanned_cable, get_audio_cable, sku_kind, pg_pool,
    list_ltd_editions, get_ltd_edition,
)


TEST_PREFIX = "SC"
TEST_SLUG = "TESTPHISH"
TEST_SKU = f"{TEST_PREFIX}-LTD-{TEST_SLUG}"
TEST_EVENT_NAME = "Phish Summer Tour Test 2026"
TEST_LENGTH = 10  # cable_skus.length is now NUMERIC(5,2)
TEST_DESCRIPTION = "10ft cotton TRS-TRS, custom forest green braid"
TEST_OPERATOR = "ADW"
TEST_SERIAL = "TESTLTD1"


def insert_ltd_edition_directly():
    """Simulate what the Shopify app's CRUD UI does: insert cable_skus row + sidecar.

    Post-Phase-3.5, cable_skus is just (sku, description, length); series and
    construction fields come from the YAML resolver at read time. The
    cable_ltd_metadata sidecar carries event_name and lifecycle state.
    """
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO cable_skus (sku, description, length)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (sku) DO UPDATE
                    SET description = EXCLUDED.description,
                        length = EXCLUDED.length
                """, (TEST_SKU, TEST_DESCRIPTION, TEST_LENGTH))

                cur.execute("""
                    INSERT INTO cable_ltd_metadata (sku, event_name, created_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (sku) DO UPDATE
                    SET event_name = EXCLUDED.event_name,
                        archived_at = NULL
                """, (TEST_SKU, TEST_EVENT_NAME, TEST_OPERATOR))
            conn.commit()
    finally:
        pg_pool.putconn(conn)


def test_ltd_scan_flow():
    print("=" * 70)
    print("Testing LTD Scan Flow")
    print("=" * 70)

    # Step 1: sku_kind classification
    print("\n1. sku_kind classification")
    print("-" * 70)
    if sku_kind(TEST_SKU) != 'ltd':
        print(f"   ❌ sku_kind({TEST_SKU!r}) returned {sku_kind(TEST_SKU)!r}, expected 'ltd'")
        return False
    print(f"   ✅ sku_kind({TEST_SKU!r}) = 'ltd'")

    # Step 2: insert LTD edition
    print(f"\n2. Inserting LTD edition {TEST_SKU}")
    print("-" * 70)
    try:
        insert_ltd_edition_directly()
        print(f"   ✅ Inserted edition with event '{TEST_EVENT_NAME}'")
    except Exception as e:
        print(f"   ❌ Insert failed: {e}")
        return False

    # Step 3: list_ltd_editions returns it
    print(f"\n3. list_ltd_editions() includes the new edition")
    print("-" * 70)
    editions = list_ltd_editions(active_only=True)
    found = next((e for e in editions if e['sku'] == TEST_SKU), None)
    if not found:
        print(f"   ❌ {TEST_SKU} not in active editions list")
        return False
    print(f"   ✅ Found: {found['slug']} — {found['event_name']} ({found['cable_count']} cables)")

    # series_prefix filter
    sc_editions = list_ltd_editions(active_only=True, series_prefix='SC')
    if not any(e['sku'] == TEST_SKU for e in sc_editions):
        print(f"   ❌ series_prefix='SC' filter excluded our SC-prefixed edition")
        return False
    tc_editions = list_ltd_editions(active_only=True, series_prefix='TC')
    if any(e['sku'] == TEST_SKU for e in tc_editions):
        print(f"   ❌ series_prefix='TC' filter incorrectly included our SC edition")
        return False
    print(f"   ✅ series_prefix filter excludes/includes correctly")

    # Step 4: get_ltd_edition single-record fetch
    print(f"\n4. get_ltd_edition({TEST_SKU})")
    print("-" * 70)
    detail = get_ltd_edition(TEST_SKU)
    if not detail:
        print(f"   ❌ get_ltd_edition returned None")
        return False
    if detail['event_name'] != TEST_EVENT_NAME:
        print(f"   ❌ event_name mismatch: got {detail['event_name']!r}")
        return False
    print(f"   ✅ Fetched: slug={detail['slug']}, event={detail['event_name']}, "
          f"active={detail['active']}, cable_count={detail['cable_count']}")

    # Step 5: register a cable against the LTD SKU
    print(f"\n5. Registering cable {TEST_SERIAL} as {TEST_SKU}")
    print("-" * 70)
    result = register_scanned_cable(
        serial_number=TEST_SERIAL,
        cable_sku=TEST_SKU,
        operator=TEST_OPERATOR,
        update_if_exists=True,
    )
    if not result.get('success'):
        print(f"   ❌ Registration failed: {result.get('message')}")
        return False
    print(f"   ✅ Registered: {result['serial_number']}")

    # Step 6: get_audio_cable surfaces event_name from sidecar
    print(f"\n6. get_audio_cable returns event_name")
    print("-" * 70)
    cable = get_audio_cable(result['serial_number'])
    if not cable:
        print(f"   ❌ Failed to retrieve cable")
        return False
    if cable.get('event_name') != TEST_EVENT_NAME:
        print(f"   ❌ event_name mismatch: got {cable.get('event_name')!r}")
        return False
    print(f"   ✅ Cable record includes event_name: {cable['event_name']!r}")
    print(f"      sku={cable['sku']}, length={cable['length']} ft")
    print(f"      description={cable.get('description')!r}")

    # Step 7: cable count incremented
    print(f"\n7. Cable count on edition incremented")
    print("-" * 70)
    detail2 = get_ltd_edition(TEST_SKU)
    if detail2['cable_count'] < 1:
        print(f"   ❌ cable_count = {detail2['cable_count']}, expected >= 1")
        return False
    print(f"   ✅ cable_count = {detail2['cable_count']}")

    print("\n" + "=" * 70)
    print("✅ ALL LTD FLOW TESTS PASSED")
    print("=" * 70)
    return True


def cleanup_test_data():
    """Remove test cable + LTD edition (cascades from cable_skus delete)."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TESTLTD%'")
            cur.execute("DELETE FROM cable_skus WHERE sku = %s", (TEST_SKU,))
            conn.commit()
            print("\n🧹 Cleaned up test data")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)


if __name__ == "__main__":
    try:
        success = test_ltd_scan_flow()
        response = input("\nKeep test data in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_data()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
