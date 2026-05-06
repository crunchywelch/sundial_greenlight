#!/usr/bin/env python3
"""Test script: register a MISC variant via get_or_create_misc_sku and verify
length + description round-trip through audio_cables → cable_skus."""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import (
    register_scanned_cable, get_audio_cable, get_or_create_misc_sku, pg_pool, sku_kind,
)


def test_misc_cable_length():
    test_serial = "TEST999"
    test_series_prefix = "TC"
    test_operator = "ADW"
    test_length = 7.5
    test_description = "dark putty houndstooth with gold connectors instead of nickel"

    print("=" * 60)
    print("Testing MISC Cable Length Storage")
    print("=" * 60)

    # Resolve a MISC sku_group (creates a new sku_group row if needed). Phase 4:
    # length is per-cable, no longer part of group identity.
    print(f"\n1. Resolving MISC sku_group for prefix {test_series_prefix}")
    print(f"   Description: {test_description}")
    misc_sku = get_or_create_misc_sku(test_series_prefix, test_description)
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
    print(f"   SKU:         {cable_record.get('sku')}")
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
    """Remove the test cable (variant SKU is left in cable_skus for dedup)."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TEST%'")
            conn.commit()
            print("\n🧹 Cleaned up test cable")
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
