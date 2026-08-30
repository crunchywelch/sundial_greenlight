#!/usr/bin/env python3
"""Test script to verify MISC cable description display (Phase 4 shape)."""

import sys
sys.path.insert(0, '/home/welch/projects/sundial_greenlight')

from greenlight.db import get_audio_cable, get_cables_for_customer


def test_misc_cable_display():
    """Test that MISC cable descriptions are properly displayed"""

    print("=" * 70)
    print("Testing MISC Cable Description Display")
    print("=" * 70)

    # Test 1: Check cable lookup
    print("\n1. Testing cable lookup (get_audio_cable)")
    print("-" * 70)
    cable = get_audio_cable('000009')

    if not cable:
        print("❌ Cable not found")
        return False

    print(f"Serial Number: {cable['serial_number']}")
    print(f"variant_sku:   {cable['variant_sku']}")
    print(f"sku_group:     {cable['sku_group']}")
    print(f"Kind:          {cable['kind']}")
    print(f"Series:        {cable['series']}")
    print(f"Length:        {cable['length']} ft")
    print(f"Pattern Name:  {cable.get('pattern_name')}")
    print(f"Description:   {cable.get('description', 'N/A')}")

    is_misc = cable.get('kind') == 'misc'
    has_description = bool(cable.get('description'))

    if is_misc and has_description:
        print("✅ MISC cable has description")
    elif not is_misc:
        print(f"⚠️  Not a MISC cable (sku_group: {cable['sku_group']})")
        return False
    else:
        print("❌ MISC cable missing description")
        return False

    # Test 2: Simulate how it displays in the cable info screen
    print("\n2. Testing cable info display formatting")
    print("-" * 70)

    serial_number = cable['serial_number']
    variant_sku = cable['variant_sku']
    series = cable['series']
    length = cable['length']
    pattern_name = cable.get('pattern_name')
    connector_display = cable.get('connector_display')
    description = cable.get('description')

    cable_info = f"""Serial Number: {serial_number}
SKU: {variant_sku}

Cable Details:
  Series: {series}
  Length: {length} ft"""
    if pattern_name:
        cable_info += f"\n  Color: {pattern_name}"
    if connector_display:
        cable_info += f"\n  Connector: {connector_display}"
    if cable.get('kind') in ('misc', 'ltd') and description:
        cable_info += f"\n  Description: {description}"

    print(cable_info)

    if "Description:" in cable_info:
        print("\n✅ Description is included in display")
    else:
        print("\n❌ Description is NOT included in display")
        return False

    # Test 3: Test customer cables display (if cable is assigned)
    print("\n3. Testing customer cable display formatting")
    print("-" * 70)

    customer_gid = cable.get('shopify_gid')
    if customer_gid:
        print(f"Cable is assigned to customer: {customer_gid}")
        cables = get_cables_for_customer(customer_gid)

        if cables:
            test_cable = next((c for c in cables if c['serial_number'] == '000009'), None)
            if test_cable:
                if test_cable.get('kind') in ('misc', 'ltd') and test_cable.get('description'):
                    cable_desc = f"{test_cable['series']} {test_cable['length']}ft - {test_cable['description']}"
                else:
                    cable_desc = f"{test_cable['series']} {test_cable['length']}ft {test_cable.get('pattern_name') or ''}".rstrip()

                print(f"Display: {test_cable['serial_number']} - {cable_desc}")

                if test_cable.get('description') in cable_desc:
                    print("✅ Description is shown in customer cable list")
                else:
                    print("❌ Description is NOT shown in customer cable list")
                    return False
            else:
                print("⚠️  Test cable not found in customer's cables")
        else:
            print("⚠️  No cables found for customer")
    else:
        print("⚠️  Cable not assigned to any customer (skipping customer display test)")

    print("\n" + "=" * 70)
    print("✅ ALL TESTS PASSED - MISC cable descriptions display correctly!")
    print("=" * 70)
    return True


if __name__ == "__main__":
    try:
        success = test_misc_cable_display()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
