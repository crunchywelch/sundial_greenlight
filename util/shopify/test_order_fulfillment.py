#!/usr/bin/env python3
"""Test order fulfillment SKU validation (Phase 5).

assign_cable_to_order computes the user-facing variant SKU from the cable's
(sku_group, prefix, length, connector_code) at validation time and matches
it against the line item SKU list. This is the trickiest piece of the
fulfillment path — silently breaking it would mean orders can't be filled
or cables get assigned to wrong orders.

Cases covered:
  - Matching variant SKU → success
  - Non-matching SKU → 'sku_mismatch' error with the computed cable SKU
  - Duplicate scan (same order) → 'duplicate' error
  - Already on a different order → 'already_assigned_order' error
"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.cable import resolve_catalog_variant
from greenlight.db import (
    register_scanned_cable, assign_cable_to_order,
    force_reassign_cable, unassign_cable, pg_pool,
)


TEST_SERIES = "Studio Classic"
TEST_PATTERN_NAME = "Pearl White"
TEST_LENGTH_STR = "10"
TEST_CONNECTOR_DISPLAY = "TS–TS"  # straight
TEST_OPERATOR = "ADW"
TEST_SERIAL = "TESTORD1"

TEST_CUSTOMER_GID = "gid://shopify/Customer/9999000000001"
TEST_ORDER_GID = "gid://shopify/Order/9999000000001"
OTHER_ORDER_GID = "gid://shopify/Order/9999000000002"


def setup_test_cable():
    """Register a fresh catalog cable to fulfill against."""
    resolved = resolve_catalog_variant(
        TEST_SERIES, TEST_PATTERN_NAME, TEST_LENGTH_STR, TEST_CONNECTOR_DISPLAY,
    )
    if not resolved:
        raise RuntimeError("resolve_catalog_variant returned None")
    result = register_scanned_cable(
        serial_number=TEST_SERIAL,
        sku_group=resolved['sku_group'],
        prefix=resolved['prefix'],
        length=resolved['length'],
        connector_code=resolved['connector_code'],
        operator=TEST_OPERATOR,
        update_if_exists=True,
    )
    if not result.get('success'):
        raise RuntimeError(f"setup register failed: {result}")
    return result['serial_number']  # returns the formatted serial


def test_order_fulfillment():
    print("=" * 70)
    print("Testing Order Fulfillment SKU Validation (Phase 5)")
    print("=" * 70)

    formatted_serial = setup_test_cable()
    expected_variant_sku = "SC-10PW"  # Pearl White, 10ft, straight
    print(f"\nSetup: registered {formatted_serial} as {expected_variant_sku}")

    # Case 1: SKU mismatch — line items don't include the cable's variant SKU
    print(f"\n1. assign_cable_to_order with non-matching line items")
    print("-" * 70)
    bad_line_items = ["SC-10GL", "SC-12RS"]  # different patterns/lengths
    result = assign_cable_to_order(
        formatted_serial, TEST_CUSTOMER_GID, TEST_ORDER_GID, bad_line_items,
    )
    if result.get('error') != 'sku_mismatch':
        print(f"   ❌ Expected error sku_mismatch, got: {result}")
        return False
    if result.get('cable_sku') != expected_variant_sku:
        print(f"   ❌ Expected cable_sku {expected_variant_sku}, got {result.get('cable_sku')}")
        return False
    print(f"   ✅ Returned sku_mismatch with cable_sku={result['cable_sku']}")

    # Case 2: SKU match — line items include the cable's variant SKU
    print(f"\n2. assign_cable_to_order with matching line items")
    print("-" * 70)
    good_line_items = ["SC-10GL", expected_variant_sku, "TC-15HP-R"]
    result = assign_cable_to_order(
        formatted_serial, TEST_CUSTOMER_GID, TEST_ORDER_GID, good_line_items,
    )
    if not result.get('success'):
        print(f"   ❌ Expected success, got: {result}")
        return False
    if result.get('sku') != expected_variant_sku:
        print(f"   ❌ Expected returned sku={expected_variant_sku}, got {result.get('sku')}")
        return False
    print(f"   ✅ Assigned successfully; returned sku={result['sku']}")

    # Case 3: Duplicate scan — already assigned to this order
    print(f"\n3. Duplicate scan to same order")
    print("-" * 70)
    result = assign_cable_to_order(
        formatted_serial, TEST_CUSTOMER_GID, TEST_ORDER_GID, good_line_items,
    )
    if result.get('error') != 'duplicate':
        print(f"   ❌ Expected error duplicate, got: {result}")
        return False
    print(f"   ✅ Returned duplicate")

    # Case 4: Already assigned to a different order
    print(f"\n4. Try to assign to a different order")
    print("-" * 70)
    result = assign_cable_to_order(
        formatted_serial, TEST_CUSTOMER_GID, OTHER_ORDER_GID, good_line_items,
    )
    if result.get('error') != 'already_assigned_order':
        print(f"   ❌ Expected error already_assigned_order, got: {result}")
        return False
    print(f"   ✅ Returned already_assigned_order with existing_order_gid="
          f"{result.get('existing_order_gid')}")

    # Case 5: Cable not found
    print(f"\n5. Non-existent serial number")
    print("-" * 70)
    result = assign_cable_to_order(
        "NOSUCHCABLE", TEST_CUSTOMER_GID, TEST_ORDER_GID, good_line_items,
    )
    if result.get('error') != 'not_found':
        print(f"   ❌ Expected error not_found, got: {result}")
        return False
    print(f"   ✅ Returned not_found")

    print("\n" + "=" * 70)
    print("✅ ALL ORDER FULFILLMENT TESTS PASSED")
    print("=" * 70)
    return True


def cleanup_test_data():
    """Remove the test cable. Order assignment fields go with it."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TESTORD%'")
            conn.commit()
            print("\n🧹 Cleaned up test cable")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)


if __name__ == "__main__":
    try:
        success = test_order_fulfillment()
        response = input("\nKeep test data in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_data()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
