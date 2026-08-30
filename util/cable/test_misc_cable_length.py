#!/usr/bin/env python3
"""Test script: register a MISC variant via get_or_create_misc_sku and verify
length + description round-trip through audio_cables → cable_skus."""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import (
    register_scanned_cable, get_audio_cable, get_or_create_misc_sku, pg_pool, sku_kind,
)


TEST_SERIAL = "TEST999"
TEST_SERIES_PREFIX = "TC"
TEST_OPERATOR = "ADW"
TEST_LENGTH = 7.5
TEST_DESCRIPTION = "dark putty houndstooth with gold connectors instead of nickel"


def test_misc_cable_length():
    test_serial = TEST_SERIAL
    test_series_prefix = TEST_SERIES_PREFIX
    test_operator = TEST_OPERATOR
    test_length = TEST_LENGTH
    test_description = TEST_DESCRIPTION

    print("=" * 60)
    print("Testing MISC Cable Length Storage")
    print("=" * 60)

    # Resolve a MISC sku_group. Each MISC group holds cables of one length;
    # the dedup key is (prefix, description, length-of-existing-cables-in-group).
    # First call (no matching cables yet) → creates a new group.
    print(f"\n1. Resolving MISC sku_group for prefix {test_series_prefix}")
    print(f"   Description: {test_description}")
    print(f"   Length:      {test_length}")
    misc_sku = get_or_create_misc_sku(test_series_prefix, test_description, test_length)
    if not misc_sku:
        print("   ❌ Failed to resolve MISC sku_group")
        return False
    print(f"   ✅ sku_group: {misc_sku}")
    assert sku_kind(misc_sku) == 'misc', f"sku_kind misclassified {misc_sku}"

    # Register a cable against the sku_group with per-cable length
    print(f"\n2. Registering cable {test_serial} as {misc_sku} ({test_length}ft)")
    result = register_scanned_cable(
        serial_number=test_serial,
        sku_group=misc_sku,
        prefix=test_series_prefix,
        length=test_length,
        connector_code='',
        operator=test_operator,
        update_if_exists=True,
    )
    if not result.get('success'):
        print(f"   ❌ Registration failed: {result.get('message')}")
        return False
    print(f"   ✅ Registered serial: {result['serial_number']}")

    # Read back via get_audio_cable and verify length + description
    print(f"\n3. Reading cable back from database")
    cable_record = get_audio_cable(result['serial_number'])
    if not cable_record:
        print("   ❌ Failed to retrieve cable")
        return False

    print(f"   Serial:      {cable_record.get('serial_number')}")
    print(f"   variant_sku: {cable_record.get('variant_sku')}")
    print(f"   sku_group:   {cable_record.get('sku_group')}")
    print(f"   Series:      {cable_record.get('series')}")
    print(f"   Length:      {cable_record.get('length')} ft")
    print(f"   Description: {cable_record.get('description')}")

    retrieved_length = cable_record.get('length')
    retrieved_desc = cable_record.get('description')

    length_ok = retrieved_length == test_length
    desc_ok = retrieved_desc == test_description

    print(f"\n   Length match:      {'✅' if length_ok else '❌'} (expected {test_length}, got {retrieved_length})")
    print(f"   Description match: {'✅' if desc_ok else '❌'}")

    if length_ok and desc_ok:
        print(f"\n{'=' * 60}\n✅ TEST PASSED\n{'=' * 60}")
        return True
    print(f"\n{'=' * 60}\n❌ TEST FAILED\n{'=' * 60}")
    return False


def cleanup_test_cable():
    """Remove the test cable + the test sku_group it spawned (only if no
    other cables remain on it — i.e., we won't delete a group that's also
    in real use)."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TEST%'")
            cur.execute("""
                DELETE FROM sku_group sg
                WHERE sg.description = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM audio_cables ac WHERE ac.sku_group = sg.sku
                  )
            """, (TEST_DESCRIPTION,))
            conn.commit()
            print("\n🧹 Cleaned up test cable + sku_group")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)


if __name__ == "__main__":
    try:
        success = test_misc_cable_length()
        response = input("\nKeep test cable in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_cable()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
