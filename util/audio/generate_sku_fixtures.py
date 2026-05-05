#!/usr/bin/env python3
"""Generate tests/sku_fixtures_prod.json from real cable_skus rows.

Runs the Python resolver against every SKU in the prod cable_skus table and
writes the (sku, expected) pairs to a separate fixture file alongside the
hand-written tests/sku_fixtures.json. Both fixture files are consumed by
both the Python and JS parity tests — synthetic + prod = full coverage.

Why have it: synthetic fixtures alone won't catch a YAML edit that breaks
back-compat for an already-shipped SKU. Regenerating this file after any
YAML change surfaces drift immediately on the next test run.

Connection: uses PGSERVICE=greenlight by default, overridable via env or
the standard PG* libpq env vars.

Usage:
    PGSERVICE=greenlight python util/audio/generate_sku_fixtures.py
"""

import json
import os
import sys
from pathlib import Path

import psycopg2

# Make `greenlight` importable when run from the repo root
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from greenlight.cable_config import parse_sku  # noqa: E402

FIXTURE_PATH = REPO_ROOT / "tests" / "sku_fixtures_prod.json"


def fetch_prod_skus(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT sku FROM cable_skus ORDER BY sku")
        return [row[0] for row in cur.fetchall()]


def build_fixture_entry(sku):
    expected = parse_sku(sku)
    return {
        "name": f"prod: {sku}",
        "sku": sku,
        "expected": expected,
    }


def main():
    service = os.environ.get("PGSERVICE", "greenlight")
    print(f"Connecting via PGSERVICE={service}...")
    try:
        conn = psycopg2.connect(service=service)
    except psycopg2.Error as e:
        print(f"❌ Connection failed: {e}")
        return 1

    try:
        skus = fetch_prod_skus(conn)
    finally:
        conn.close()

    print(f"Found {len(skus)} distinct SKUs in cable_skus")

    entries = [build_fixture_entry(sku) for sku in skus]

    # Self-check: count by kind, surface anything unexpected.
    by_kind = {}
    null_kind = []
    null_series = []
    null_pattern = []
    for entry in entries:
        ex = entry["expected"]
        kind = ex.get("kind")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if kind is None:
            null_kind.append(entry["sku"])
            continue
        if ex.get("series") is None:
            null_series.append(entry["sku"])
        if kind == "catalog" and ex.get("pattern_name") is None:
            null_pattern.append(entry["sku"])

    print()
    print("Breakdown by kind:")
    for kind, count in sorted(by_kind.items(), key=lambda kv: (kv[0] is None, kv[0] or "")):
        print(f"  {str(kind):>10}: {count}")

    issues = False
    if null_kind:
        issues = True
        print()
        print(f"⚠️  {len(null_kind)} SKU(s) returned kind=None (resolver gap!):")
        for sku in null_kind[:20]:
            print(f"    {sku}")
        if len(null_kind) > 20:
            print(f"    ... and {len(null_kind) - 20} more")

    if null_series:
        issues = True
        print()
        print(f"⚠️  {len(null_series)} SKU(s) parsed but have unknown series prefix:")
        for sku in null_series[:20]:
            print(f"    {sku}")
        if len(null_series) > 20:
            print(f"    ... and {len(null_series) - 20} more")

    if null_pattern:
        # Less alarming — could be expected for some catalog rows. Flag for review.
        print()
        print(f"ℹ️  {len(null_pattern)} catalog SKU(s) parsed but have unknown pattern_code:")
        for sku in null_pattern[:20]:
            print(f"    {sku}")
        if len(null_pattern) > 20:
            print(f"    ... and {len(null_pattern) - 20} more")

    # Write the fixture file
    FIXTURE_PATH.write_text(json.dumps(entries, indent=2) + "\n")
    print()
    print(f"✅ Wrote {len(entries)} entries to {FIXTURE_PATH.relative_to(REPO_ROOT)}")

    if issues:
        print()
        print("Resolver gaps detected (kind=None or unknown series). Review and fix")
        print("the resolver / YAML / fixtures before consumer migrations land.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
