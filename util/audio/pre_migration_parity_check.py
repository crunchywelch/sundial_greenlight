#!/usr/bin/env python3
"""Pre-migration parity check for Phase 3.5 column drops.

Compares the YAML resolver's output against the existing cable_skus column
values for every row. The check is intentionally strict for catalog rows
(any divergence aborts the migration) and lenient for variant rows: MISC
and LTD inherit YAML defaults for series/core_cable/braid_material at row-
creation time and may carry sentinel values like 'Varies' or 'Limited
Edition' that the resolver doesn't reproduce. Per the Phase 3.5 design
decision, those variant divergences are accepted as legacy garbage that
disappears with the column drops.

Run this BEFORE the migration transaction. Exit code 0 means the migration
is safe to run; non-zero means investigate the catalog drift first.

Usage:
    PGSERVICE=greenlight python util/audio/pre_migration_parity_check.py
"""

import os
import sys
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from greenlight.cable_config import parse_sku, series_data_for_prefix  # noqa: E402


CATALOG_FIELDS = ('series', 'core_cable', 'braid_material',
                  'color_pattern', 'connector_type', 'length')


def normalize_length(value):
    """DB stores length as TEXT (e.g. '12'); resolver returns int. Compare
    numerically so '12' == 12 and '12.0' == 12.0."""
    if value is None:
        return None
    try:
        return int(value) if str(value).isdigit() else float(value)
    except (TypeError, ValueError):
        return value


def check_catalog_row(sku, db_values):
    """Return dict of field_name → (db, resolver) for any divergence on a
    catalog row, or None if the row matches."""
    parsed = parse_sku(sku)
    sd = series_data_for_prefix(parsed.get('series_prefix') or '')

    resolver_values = {
        'series': parsed.get('series'),
        'core_cable': sd.get('core_cable') if sd else None,
        'braid_material': sd.get('braid_material') if sd else None,
        'color_pattern': parsed.get('pattern_name'),
        'connector_type': parsed.get('connector_display'),
        'length': parsed.get('length'),
    }

    diffs = {}
    for field in CATALOG_FIELDS:
        db_v = db_values[field]
        res_v = resolver_values[field]
        if field == 'length':
            db_v = normalize_length(db_v)
        if db_v != res_v:
            diffs[field] = (db_v, res_v)
    return diffs or None


def main():
    service = os.environ.get('PGSERVICE', 'greenlight')
    print(f'Connecting via PGSERVICE={service}...')
    try:
        conn = psycopg2.connect(service=service)
    except psycopg2.Error as e:
        print(f'❌ Connection failed: {e}')
        return 2

    try:
        with conn.cursor() as cur:
            cur.execute('''
                SELECT sku, series, core_cable, braid_material,
                       color_pattern, connector_type, length
                FROM cable_skus
                ORDER BY sku
            ''')
            rows = cur.fetchall()
    finally:
        conn.close()

    n_catalog = 0
    n_variant = 0
    catalog_diffs = []
    parse_failures = []

    for sku, series, core, braid, color, conn_t, length in rows:
        parsed = parse_sku(sku)
        kind = parsed.get('kind')
        if kind is None:
            parse_failures.append(sku)
            continue
        if kind in ('misc', 'ltd'):
            n_variant += 1
            continue
        n_catalog += 1
        diffs = check_catalog_row(sku, {
            'series': series, 'core_cable': core, 'braid_material': braid,
            'color_pattern': color, 'connector_type': conn_t, 'length': length,
        })
        if diffs:
            catalog_diffs.append((sku, diffs))

    print(f'Inspected {n_catalog} catalog rows, {n_variant} variant rows '
          f'(variant divergence accepted per design)')

    if parse_failures:
        print()
        print(f'❌ {len(parse_failures)} SKU(s) the resolver could not parse — '
              f'fix the resolver or these rows before migrating:')
        for sku in parse_failures[:20]:
            print(f'    {sku}')

    if catalog_diffs:
        print()
        print(f'❌ {len(catalog_diffs)} catalog row(s) diverge from resolver:')
        for sku, d in catalog_diffs[:20]:
            print(f'  {sku}:')
            for field, (db_v, res_v) in d.items():
                print(f'    {field}: db={db_v!r} resolver={res_v!r}')
        if len(catalog_diffs) > 20:
            print(f'  ... and {len(catalog_diffs) - 20} more')

    if catalog_diffs or parse_failures:
        print()
        print('Migration aborted. Investigate the divergence before re-running.')
        return 1

    # Length backfill safety check: every variant row's length must parse to numeric
    print()
    print('Length backfill check (variants must have parseable numeric length text):')
    bad_lengths = []
    for sku, _, _, _, _, _, length in rows:
        parsed = parse_sku(sku)
        if parsed.get('kind') not in ('misc', 'ltd'):
            continue
        if length is None:
            bad_lengths.append((sku, None))
            continue
        try:
            float(str(length).strip())
        except (TypeError, ValueError):
            bad_lengths.append((sku, length))

    if bad_lengths:
        print(f'❌ {len(bad_lengths)} variant row(s) have unparseable length:')
        for sku, length in bad_lengths[:20]:
            print(f'    {sku}: length={length!r}')
        return 1

    print('  ✅ all variant lengths parse as numeric')
    print()
    print('✅ Pre-migration parity check passed. Safe to run the migration.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
