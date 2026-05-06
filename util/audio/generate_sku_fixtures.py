#!/usr/bin/env python3
"""Generate tests/sku_fixtures_prod.json from real prod data (Phase 4).

Walks both sku_group and audio_cables, emitting:
  - one 'group' fixture per sku_group row (parses sku via parse_group_sku)
  - one 'variant' fixture per distinct (sku_group, length, connector_code)
    tuple from audio_cables (variant SKU built via format_variant_sku, then
    parsed back via parse_variant_sku)
  - one 'round_trip' fixture per distinct variant SKU, asserting
    format_variant_sku(parse_variant_sku(sku)) == sku

The same fixture file is consumed by both the Python and JS parity tests —
synthetic + prod = full coverage. Catches resolver gaps and YAML drift
that the synthetic fixtures alone won't.

Connection: uses PGSERVICE=greenlight by default.

Usage:
    PGSERVICE=greenlight python util/audio/generate_sku_fixtures.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from greenlight.cable_config import (  # noqa: E402
    parse_group_sku, parse_variant_sku, format_variant_sku,
)

FIXTURE_PATH = REPO_ROOT / "tests" / "sku_fixtures_prod.json"


def fetch_groups(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT sku FROM sku_group ORDER BY sku")
        return [row[0] for row in cur.fetchall()]


def fetch_variant_tuples(conn):
    """Return distinct (sku_group, length, connector_code) tuples from audio_cables."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT sku_group, length, connector_code
            FROM audio_cables
            ORDER BY sku_group, length, connector_code
        """)
        return cur.fetchall()


def build_group_entry(sku):
    return {
        'name': f'prod group: {sku}',
        'type': 'group',
        'sku': sku,
        'expected': parse_group_sku(sku),
    }


def build_variant_entry(group_sku, length, connector_code):
    # format_variant_sku takes int/float length; DB returns Decimal.
    length_val = float(length) if length is not None else None
    if length_val is not None and length_val.is_integer():
        length_val = int(length_val)
    variant_sku = format_variant_sku(
        group_sku=group_sku, length=length_val, connector_code=connector_code,
    )
    return variant_sku, {
        'name': f'prod variant: {variant_sku}',
        'type': 'variant',
        'sku': variant_sku,
        'expected': parse_variant_sku(variant_sku),
    }


def build_round_trip_entry(variant_sku):
    return {
        'name': f'prod round-trip: {variant_sku}',
        'type': 'round_trip',
        'sku': variant_sku,
    }


def main():
    service = os.environ.get('PGSERVICE', 'greenlight')
    print(f'Connecting via PGSERVICE={service}...')
    try:
        conn = psycopg2.connect(service=service)
    except psycopg2.Error as e:
        print(f'❌ Connection failed: {e}')
        return 1

    try:
        group_skus = fetch_groups(conn)
        variant_tuples = fetch_variant_tuples(conn)
    finally:
        conn.close()

    entries = []

    # Groups
    group_failures = []
    for sku in group_skus:
        entry = build_group_entry(sku)
        entries.append(entry)
        if entry['expected'].get('kind') is None:
            group_failures.append(sku)

    # Variants (deduplicate by computed variant_sku — multiple cables share a variant)
    seen_variants = set()
    variant_entries = []
    round_trip_entries = []
    variant_failures = []
    for group_sku, length, connector_code in variant_tuples:
        variant_sku, entry = build_variant_entry(group_sku, length, connector_code)
        if variant_sku is None:
            variant_failures.append((group_sku, length, connector_code))
            continue
        if variant_sku in seen_variants:
            continue
        seen_variants.add(variant_sku)
        variant_entries.append(entry)
        round_trip_entries.append(build_round_trip_entry(variant_sku))

    entries.extend(variant_entries)
    entries.extend(round_trip_entries)

    print()
    print(f'Group entries:    {len(group_skus)}')
    print(f'Variant entries:  {len(variant_entries)}  (from {len(variant_tuples)} distinct (group,length,conn) tuples)')
    print(f'Round-trip:       {len(round_trip_entries)}')
    print(f'Total:            {len(entries)}')

    issues = False
    if group_failures:
        issues = True
        print()
        print(f'⚠️  {len(group_failures)} group SKU(s) failed to parse:')
        for sku in group_failures[:20]:
            print(f'    {sku}')

    if variant_failures:
        issues = True
        print()
        print(f'⚠️  {len(variant_failures)} variant tuple(s) failed format_variant_sku:')
        for tup in variant_failures[:20]:
            print(f'    {tup}')

    FIXTURE_PATH.write_text(json.dumps(entries, indent=2) + '\n')
    print()
    print(f'✅ Wrote {len(entries)} entries to {FIXTURE_PATH.relative_to(REPO_ROOT)}')

    return 1 if issues else 0


if __name__ == '__main__':
    sys.exit(main())
