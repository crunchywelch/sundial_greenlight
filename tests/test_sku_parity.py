#!/usr/bin/env python3
"""Parity test for the Python SKU resolver.

Loads tests/sku_fixtures.json and asserts greenlight.cable_config.parse_sku
returns the expected dict for every fixture entry. The same fixture file is
consumed by the JS resolver's parity test (shopify_app/...). Same input,
same output, enforced on both sides.

Run: pytest tests/test_sku_parity.py  (or python tests/test_sku_parity.py)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from greenlight.cable_config import parse_sku


FIXTURE_PATH = Path(__file__).resolve().parent / "sku_fixtures.json"


def load_fixtures():
    with open(FIXTURE_PATH) as f:
        return json.load(f)


def run_parity_check():
    fixtures = load_fixtures()
    failures = []

    for entry in fixtures:
        name = entry.get('name', entry['sku'])
        sku = entry['sku']
        expected = entry['expected']
        actual = parse_sku(sku)

        if actual != expected:
            failures.append({
                'name': name,
                'sku': sku,
                'expected': expected,
                'actual': actual,
            })

    return fixtures, failures


def test_sku_parity():
    """Pytest entry point — passes iff every fixture matches."""
    fixtures, failures = run_parity_check()
    if failures:
        msg_lines = [f"\n{len(failures)}/{len(fixtures)} SKU fixtures failed:"]
        for f in failures:
            msg_lines.append(f"\n  • {f['name']}")
            msg_lines.append(f"    sku:      {f['sku']!r}")
            msg_lines.append(f"    expected: {f['expected']}")
            msg_lines.append(f"    actual:   {f['actual']}")
        raise AssertionError('\n'.join(msg_lines))


def main():
    """Standalone runner — prints results and exits non-zero on failure."""
    fixtures, failures = run_parity_check()
    print(f"Loaded {len(fixtures)} fixtures from {FIXTURE_PATH.name}")
    print()

    if not failures:
        print(f"✅ All {len(fixtures)} fixtures pass")
        return 0

    print(f"❌ {len(failures)}/{len(fixtures)} fixtures failed:\n")
    for f in failures:
        print(f"  • {f['name']}")
        print(f"    sku:      {f['sku']!r}")
        print(f"    expected: {f['expected']}")
        print(f"    actual:   {f['actual']}")
        print()
    return 1


if __name__ == '__main__':
    sys.exit(main())
