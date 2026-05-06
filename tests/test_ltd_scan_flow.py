#!/usr/bin/env python3
"""Test LTD scan flow (Phase 4): insert an LTD edition into sku_group, register
a cable against it with length+connector_code on audio_cables, verify
get_audio_cable surfaces description (event_name equivalent), and confirm
sku_kind / list_ltd_editions work as expected.

Phase 4 model:
  - LTD edition is just a sku_group row (sku, description, archived_at).
    cable_ltd_metadata is gone — description carries event_name.
  - Each cable carries its own length + connector_code on audio_cables.
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
TEST_DESCRIPTION = "Phish Summer Tour Test 2026"
TEST_OPERATOR = "ADW"
TEST_SERIAL = "TESTLTD1"
TEST_LENGTH = 10.0
TEST_CONNECTOR_CODE = ""  # straight


def insert_ltd_edition_directly():
    """Simulate what the Shopify app's CRUD UI does: insert a sku_group row.

    Phase 4: a single row in sku_group with (sku, description) is the entire
    LTD edition. Length and connector_code live on audio_cables per-cable.
    """
    conn = pg_pool.getconn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO sku_group (sku, description)
                    VALUES (%s, %s)
                    ON CONFLICT (sku) DO UPDATE
                    SET description = EXCLUDED.description,
                        archived_at = NULL
                """, (TEST_SKU, TEST_DESCRIPTION))
            conn.commit()
    finally:
        pg_pool.putconn(conn)


def test_ltd_scan_flow():
    print("=" * 70)
    print("Testing LTD Scan Flow (Phase 4)")
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
        print(f"   ✅ Inserted edition with description '{TEST_DESCRIPTION}'")
    except Exception as e:
        print(f"   ❌ Insert failed: {e}")
        return False

    # Step 3: list_ltd_editions returns it
    print("\n3. list_ltd_editions() includes the new edition")
    print("-" * 70)
    editions = list_ltd_editions(active_only=True)
    found = next((e for e in editions if e['sku_group'] == TEST_SKU), None)
    if not found:
        print(f"   ❌ {TEST_SKU} not in active editions list")
        return False
    print(f"   ✅ Found: {found['slug']} — {found['description']} ({found['cable_count']} cables)")

    sc_editions = list_ltd_editions(active_only=True, series_prefix='SC')
    if not any(e['sku_group'] == TEST_SKU for e in sc_editions):
        print("   ❌ series_prefix='SC' filter excluded our SC-prefixed edition")
        return False
    tc_editions = list_ltd_editions(active_only=True, series_prefix='TC')
    if any(e['sku_group'] == TEST_SKU for e in tc_editions):
        print("   ❌ series_prefix='TC' filter incorrectly included our SC edition")
        return False
    print("   ✅ series_prefix filter excludes/includes correctly")

    # Step 4: get_ltd_edition single-record fetch
    print(f"\n4. get_ltd_edition({TEST_SKU})")
    print("-" * 70)
    detail = get_ltd_edition(TEST_SKU)
    if not detail:
        print("   ❌ get_ltd_edition returned None")
        return False
    if detail['description'] != TEST_DESCRIPTION:
        print(f"   ❌ description mismatch: got {detail['description']!r}")
        return False
    print(f"   ✅ Fetched: slug={detail['slug']}, description={detail['description']}, "
          f"active={detail['active']}, cable_count={detail['cable_count']}")

    # Step 5: register a cable with per-cable length + connector
    print(f"\n5. Registering cable {TEST_SERIAL} as {TEST_SKU} ({TEST_LENGTH}ft, straight)")
    print("-" * 70)
    result = register_scanned_cable(
        serial_number=TEST_SERIAL,
        sku_group=TEST_SKU,
        length=TEST_LENGTH,
        connector_code=TEST_CONNECTOR_CODE,
        operator=TEST_OPERATOR,
        update_if_exists=True,
    )
    if not result.get('success'):
        print(f"   ❌ Registration failed: {result.get('message')}")
        return False
    print(f"   ✅ Registered: {result['serial_number']}")

    # Step 6: get_audio_cable returns full enriched record
    print("\n6. get_audio_cable returns the new cable with description and length")
    print("-" * 70)
    cable = get_audio_cable(result['serial_number'])
    if not cable:
        print("   ❌ Failed to retrieve cable")
        return False
    if cable.get('description') != TEST_DESCRIPTION:
        print(f"   ❌ description mismatch: got {cable.get('description')!r}")
        return False
    if cable.get('length') != TEST_LENGTH:
        print(f"   ❌ length mismatch: got {cable.get('length')!r}")
        return False
    if cable.get('sku_group') != TEST_SKU:
        print(f"   ❌ sku_group mismatch: got {cable.get('sku_group')!r}")
        return False
    print(f"   ✅ Cable record: sku_group={cable['sku_group']}, length={cable['length']}, "
          f"connector_code={cable['connector_code']!r}")
    print(f"      description={cable['description']!r}")

    # Step 7: cable count incremented
    print("\n7. Cable count on edition incremented")
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
    """Remove the test cable + LTD edition."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TESTLTD%'")
            cur.execute("DELETE FROM sku_group WHERE sku = %s", (TEST_SKU,))
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
