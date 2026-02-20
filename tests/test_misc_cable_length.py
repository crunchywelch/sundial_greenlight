#!/usr/bin/env python3
"""Test script to verify MISC cable length storage and retrieval"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import register_scanned_cable, get_audio_cable, pg_pool

def test_misc_cable_length():
    """Test registering and retrieving a MISC cable with custom length"""

    # Test data
    test_serial = "TEST999"
    test_sku = "TC-MISC"
    test_operator = "ADW"
    test_length = 7.5  # Custom length in feet
    test_description = "dark putty houndstooth with gold connectors instead of nickel"

    print("=" * 60)
    print("Testing MISC Cable Length Storage")
    print("=" * 60)

    # Register the cable with custom length
    print(f"\n1. Registering MISC cable:")
    print(f"   Serial: {test_serial}")
    print(f"   SKU: {test_sku}")
    print(f"   Length: {test_length} ft")
    print(f"   Description: {test_description}")

    result = register_scanned_cable(
        serial_number=test_serial,
        cable_sku=test_sku,
        operator=test_operator,
        update_if_exists=True,  # Allow updating if exists
        description=test_description,
        length=test_length
    )

    if not result.get('success'):
        print(f"\n   ❌ Registration failed: {result.get('message')}")
        return False

    print(f"   ✅ Registration successful!")
    print(f"   Serial: {result['serial_number']}")

    # Retrieve the cable and verify length
    print(f"\n2. Retrieving cable from database...")
    cable_record = get_audio_cable(result['serial_number'])

    if not cable_record:
        print(f"   ❌ Failed to retrieve cable")
        return False

    print(f"   ✅ Cable retrieved successfully!")
    print(f"\n3. Verifying cable data:")
    print(f"   Serial Number: {cable_record.get('serial_number')}")
    print(f"   SKU: {cable_record.get('sku')}")
    print(f"   Series: {cable_record.get('series')}")
    print(f"   Length: {cable_record.get('length')} ft")
    print(f"   Description: {cable_record.get('description')}")

    # Verify length matches what we set
    retrieved_length = cable_record.get('length')
    if retrieved_length == test_length:
        print(f"\n   ✅ Length matches! Expected {test_length} ft, got {retrieved_length} ft")
        print(f"\n{'=' * 60}")
        print("✅ TEST PASSED - MISC cable length is stored and retrieved correctly!")
        print("=" * 60)
        return True
    else:
        print(f"\n   ❌ Length mismatch! Expected {test_length} ft, got {retrieved_length} ft")
        print(f"\n{'=' * 60}")
        print("❌ TEST FAILED")
        print("=" * 60)
        return False

def cleanup_test_cable():
    """Remove test cable from database"""
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

        # Ask if user wants to keep or clean up test data
        response = input("\nKeep test cable in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_cable()

        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
