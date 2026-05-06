#!/usr/bin/env python3
"""Test the complete MISC cable flow: resolve variant SKU, register cable, verify display."""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import (
    register_scanned_cable, get_audio_cable, get_or_create_misc_sku, pg_pool,
)


TEST_SERIAL = "TESTFLOW"
TEST_SERIES_PREFIX = "SC"
TEST_OPERATOR = "ADW"
TEST_LENGTH = 12.0
TEST_DESCRIPTION = "custom blue/orange pattern with Neutrik gold connectors"


def test_complete_misc_flow():
    test_serial = TEST_SERIAL
    test_series_prefix = TEST_SERIES_PREFIX
    test_operator = TEST_OPERATOR
    test_length = TEST_LENGTH
    test_description = TEST_DESCRIPTION

    print("=" * 70)
    print("Testing Complete MISC Cable Flow")
    print("=" * 70)

    # Step 1: Resolve a MISC sku_group (length is part of dedup key)
    print(f"\n1. Resolving MISC sku_group for prefix {test_series_prefix}")
    print("-" * 70)
    misc_sku = get_or_create_misc_sku(test_series_prefix, test_description, test_length)
    if not misc_sku:
        print("   ❌ Failed to resolve MISC sku_group")
        return False
    print(f"   ✅ sku_group: {misc_sku}")

    # Step 2: Register cable with per-cable length and connector
    print(f"\n2. Registering cable {test_serial} as {misc_sku} ({test_length}ft)")
    print("-" * 70)
    result = register_scanned_cable(
        serial_number=test_serial,
        sku_group=misc_sku,
        length=test_length,
        connector_code='',
        operator=test_operator,
        update_if_exists=True,
    )

    if not result.get('success'):
        print(f"\n   ❌ Registration failed: {result.get('message')}")
        return False

    print(f"   ✅ Registered: {result['serial_number']}")

    # Step 3: Retrieve and verify
    print(f"\n3. Retrieving cable")
    print("-" * 70)
    cable = get_audio_cable(result['serial_number'])

    if not cable:
        print("   ❌ Failed to retrieve cable")
        return False

    print(f"   ✅ Retrieved successfully")
    print(f"\n   Serial:      {cable['serial_number']}")
    print(f"   variant_sku: {cable['variant_sku']}")
    print(f"   sku_group:   {cable['sku_group']}")
    print(f"   Series:      {cable['series']}")
    print(f"   Length:      {cable['length']} ft")
    print(f"   Description: {cable.get('description')}")

    # Step 4: Verify display format uses sku_kind for MISC gating
    print(f"\n4. Display format verification")
    print("-" * 70)

    display = (
        f"  Series: {cable['series']}\n"
        f"  Length: {cable['length']} ft\n"
        f"  Pattern: {cable.get('pattern_name')}\n"
        f"  Connector: {cable.get('connector_display')}"
    )

    if cable.get('kind') in ('misc', 'ltd') and cable.get('description'):
        display += f"\n  Description: {cable['description']}"

    print(display)

    length_correct = cable['length'] == test_length
    description_correct = cable.get('description') == test_description
    misc_recognized = cable.get('kind') == 'misc'

    print(f"\n   Length correct:      {'✅' if length_correct else '❌'} ({cable['length']} ft)")
    print(f"   Description correct: {'✅' if description_correct else '❌'}")
    print(f"   sku_kind recognized: {'✅' if misc_recognized else '❌'}")

    if length_correct and description_correct and misc_recognized:
        print("\n" + "=" * 70)
        print("✅ COMPLETE FLOW TEST PASSED!")
        print("=" * 70)
        return True
    print("\n" + "=" * 70)
    print("❌ TEST FAILED")
    print("=" * 70)
    return False


def cleanup_test_cable():
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TESTFLOW%'")
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
        success = test_complete_misc_flow()
        response = input("\nKeep test cable in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_cable()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
