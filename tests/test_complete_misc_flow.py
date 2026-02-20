#!/usr/bin/env python3
"""Test complete MISC cable flow: register with custom length and description, then view"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import register_scanned_cable, get_audio_cable, pg_pool

def test_complete_misc_flow():
    """Test registering and viewing a MISC cable with custom length and description"""

    # Test data
    test_serial = "TESTFLOW"
    test_sku = "SC-MISC"
    test_operator = "ADW"
    test_length = 12.0
    test_description = "custom blue/orange pattern with Neutrik gold connectors"

    print("=" * 70)
    print("Testing Complete MISC Cable Flow")
    print("=" * 70)

    # Step 1: Register cable
    print(f"\n1. Registering MISC cable")
    print("-" * 70)
    print(f"   Serial: {test_serial}")
    print(f"   SKU: {test_sku}")
    print(f"   Length: {test_length} ft")
    print(f"   Description: {test_description}")

    result = register_scanned_cable(
        serial_number=test_serial,
        cable_sku=test_sku,
        operator=test_operator,
        update_if_exists=True,
        description=test_description,
        length=test_length
    )

    if not result.get('success'):
        print(f"\n   ❌ Registration failed: {result.get('message')}")
        return False

    print(f"\n   ✅ Registered: {result['serial_number']}")

    # Step 2: Retrieve and verify
    print(f"\n2. Retrieving cable")
    print("-" * 70)
    cable = get_audio_cable(result['serial_number'])

    if not cable:
        print("   ❌ Failed to retrieve cable")
        return False

    print(f"   ✅ Retrieved successfully")
    print(f"\n   Serial: {cable['serial_number']}")
    print(f"   SKU: {cable['sku']}")
    print(f"   Series: {cable['series']}")
    print(f"   Length: {cable['length']} ft")
    print(f"   Description: {cable.get('description')}")

    # Step 3: Verify display format
    print(f"\n3. Display format verification")
    print("-" * 70)

    # Simulate cable info display
    display = f"""  Series: {cable['series']}
  Length: {cable['length']} ft
  Color: {cable['color_pattern']}
  Connector: {cable['connector_type']}"""

    if cable['sku'].endswith('-MISC') and cable.get('description'):
        display += f"\n  Description: {cable['description']}"

    print(display)

    # Verify both length and description are correct
    length_correct = cable['length'] == test_length
    description_correct = cable.get('description') == test_description

    print(f"\n   Length correct: {'✅' if length_correct else '❌'} ({cable['length']} ft)")
    print(f"   Description correct: {'✅' if description_correct else '❌'}")

    if length_correct and description_correct:
        print("\n" + "=" * 70)
        print("✅ COMPLETE FLOW TEST PASSED!")
        print("MISC cables now correctly store and display both custom length and description")
        print("=" * 70)
        return True
    else:
        print("\n" + "=" * 70)
        print("❌ TEST FAILED")
        print("=" * 70)
        return False

def cleanup_test_cable():
    """Remove test cable from database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TESTFLOW%'")
            conn.commit()
            print("\n🧹 Cleaned up test cable")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)

if __name__ == "__main__":
    try:
        success = test_complete_misc_flow()

        # Clean up test data
        response = input("\nKeep test cable in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_cable()

        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
