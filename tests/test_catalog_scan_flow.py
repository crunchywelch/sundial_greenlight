#!/usr/bin/env python3
"""Test catalog scan flow (Phase 5): exercise resolve_catalog_variant +
register_scanned_cable for a catalog combo.

Walks the same path the screen flow does:
  1. Operator picks (series, pattern, length, connector) from YAML lists.
  2. resolve_catalog_variant maps these to (sku_group, prefix, length,
     connector_code). Catalog group SKUs are seeded by the Phase 5 migration.
  3. register_scanned_cable inserts the audio_cables row (prefix lives there).
  4. get_audio_cable returns the enriched record with variant_sku derived.
  5. Looking up by variant SKU also works (parse_variant_sku → sku_group).
"""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.cable import resolve_catalog_variant
from greenlight.cable_config import format_variant_sku, parse_variant_sku
from greenlight.db import (
    register_scanned_cable, get_audio_cable, pg_pool,
    get_available_count_for_sku,
)


# Canonical inputs from the YAML config
TEST_SERIES = "Studio Classic"
TEST_PATTERN_NAME = "Goldline"   # SC's rayon pattern
TEST_LENGTH_STR = "12"           # one of SC's lengths (from YAML)
TEST_CONNECTOR_DISPLAY = "RA–TS"  # right-angle option
TEST_OPERATOR = "ADW"
TEST_SERIAL = "TESTCAT1"


def test_catalog_scan_flow():
    print("=" * 70)
    print("Testing Catalog Scan Flow (Phase 5)")
    print("=" * 70)

    # Step 1: resolve the (series, pattern, length, connector) tuple
    print(f"\n1. Resolving ({TEST_SERIES}, {TEST_PATTERN_NAME}, "
          f"{TEST_LENGTH_STR}ft, {TEST_CONNECTOR_DISPLAY})")
    print("-" * 70)
    resolved = resolve_catalog_variant(
        TEST_SERIES, TEST_PATTERN_NAME, TEST_LENGTH_STR, TEST_CONNECTOR_DISPLAY,
    )
    if not resolved:
        print("   ❌ resolve_catalog_variant returned None")
        return False
    sku_group = resolved['sku_group']
    prefix = resolved['prefix']
    length = resolved['length']
    connector_code = resolved['connector_code']
    print(f"   ✅ sku_group={sku_group}, prefix={prefix}, length={length}, "
          f"connector_code={connector_code!r}")

    if sku_group != "GL":
        print(f"   ❌ Expected sku_group GL, got {sku_group}")
        return False
    if prefix != "SC":
        print(f"   ❌ Expected prefix SC, got {prefix}")
        return False
    if connector_code != "-R":
        print(f"   ❌ Expected connector_code '-R', got {connector_code!r}")
        return False

    # Step 2: confirm the sku_group row exists (seeded by Phase 5 migration)
    print(f"\n2. Verifying sku_group row exists")
    print("-" * 70)
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sku, description FROM sku_group WHERE sku = %s", (sku_group,),
            )
            row = cur.fetchone()
    finally:
        pg_pool.putconn(conn)

    if not row:
        print(f"   ❌ sku_group {sku_group} not seeded — Phase 5 migration incomplete?")
        return False
    print(f"   ✅ sku_group row: sku={row[0]}, description={row[1]!r}")

    # Step 3: register a cable
    print(f"\n3. Registering cable {TEST_SERIAL} as {sku_group} "
          f"(prefix {prefix}, {length}ft, connector {connector_code!r})")
    print("-" * 70)
    result = register_scanned_cable(
        serial_number=TEST_SERIAL,
        sku_group=sku_group,
        prefix=prefix,
        length=length,
        connector_code=connector_code,
        operator=TEST_OPERATOR,
        update_if_exists=True,
    )
    if not result.get('success'):
        print(f"   ❌ Registration failed: {result.get('message')}")
        return False
    print(f"   ✅ Registered: {result['serial_number']}")

    # Step 4: read back and verify enriched record
    print(f"\n4. get_audio_cable returns the enriched record")
    print("-" * 70)
    cable = get_audio_cable(result['serial_number'])
    if not cable:
        print("   ❌ Failed to retrieve cable")
        return False

    expected_variant_sku = "SC-12GL-R"
    if cable.get('variant_sku') != expected_variant_sku:
        print(f"   ❌ variant_sku mismatch: got {cable.get('variant_sku')!r}, "
              f"expected {expected_variant_sku!r}")
        return False
    if cable.get('sku_group') != sku_group:
        print(f"   ❌ sku_group mismatch: got {cable.get('sku_group')!r}")
        return False
    if cable.get('length') != length:
        print(f"   ❌ length mismatch: got {cable.get('length')!r}")
        return False
    if cable.get('kind') != 'catalog':
        print(f"   ❌ kind mismatch: got {cable.get('kind')!r}")
        return False
    if cable.get('pattern_name') != TEST_PATTERN_NAME:
        print(f"   ❌ pattern_name mismatch: got {cable.get('pattern_name')!r}")
        return False
    if cable.get('connector_display') != TEST_CONNECTOR_DISPLAY:
        print(f"   ❌ connector_display mismatch: got {cable.get('connector_display')!r}")
        return False
    print(f"   ✅ variant_sku = {cable['variant_sku']}")
    print(f"   ✅ sku_group   = {cable['sku_group']}")
    print(f"   ✅ kind        = {cable['kind']}")
    print(f"   ✅ pattern_name= {cable['pattern_name']}")
    print(f"   ✅ connector_display = {cable['connector_display']}")
    print(f"   ✅ core_cable  = {cable['core_cable']}")

    # Step 5: variant_sku round-trip identity
    print(f"\n5. Variant SKU round-trip identity")
    print("-" * 70)
    parsed = parse_variant_sku(expected_variant_sku)
    if parsed.get('group_sku') != sku_group:
        print(f"   ❌ parse_variant_sku → group_sku mismatch")
        return False
    rebuilt = format_variant_sku(
        group_sku=parsed['group_sku'], prefix=parsed['prefix'],
        length=parsed['length'], connector_code=parsed['connector_code'],
    )
    if rebuilt != expected_variant_sku:
        print(f"   ❌ format_variant_sku round-trip failed: {rebuilt!r}")
        return False
    print(f"   ✅ {expected_variant_sku} → parse → format → {rebuilt}")

    # Step 6: get_available_count_for_sku accepts the variant SKU and finds the cable
    print(f"\n6. get_available_count_for_sku({expected_variant_sku!r})")
    print("-" * 70)
    # Count is gated on test_passed=TRUE; the cable just registered hasn't been
    # tested yet, so we expect 0 (test_passed is NULL for fresh registers).
    count = get_available_count_for_sku(expected_variant_sku)
    print(f"   ℹ️  count = {count} (cable just registered, test_passed=NULL → not counted)")

    # Idempotency: re-register the same serial with update_if_exists=True
    print(f"\n7. Re-register same serial (update path)")
    print("-" * 70)
    result2 = register_scanned_cable(
        serial_number=TEST_SERIAL,
        sku_group=sku_group,
        prefix=prefix,
        length=length,
        connector_code=connector_code,
        operator=TEST_OPERATOR,
        update_if_exists=True,
    )
    if not result2.get('success') or not result2.get('updated'):
        print(f"   ❌ Update path didn't fire as expected: {result2}")
        return False
    print("   ✅ update_if_exists=True hits the UPDATE branch")

    print("\n" + "=" * 70)
    print("✅ ALL CATALOG FLOW TESTS PASSED")
    print("=" * 70)
    return True


def cleanup_test_data():
    """Remove the test cable. The sku_group row stays — it might already
    have been seeded by another cable, and dropping it would cascade."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM audio_cables WHERE serial_number LIKE 'TESTCAT%'")
            conn.commit()
            print("\n🧹 Cleaned up test cable")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")
        conn.rollback()
    finally:
        pg_pool.putconn(conn)


if __name__ == "__main__":
    try:
        success = test_catalog_scan_flow()
        response = input("\nKeep test data in database? (y/n): ").strip().lower()
        if response != 'y':
            cleanup_test_data()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
