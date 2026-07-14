#!/usr/bin/env python3
"""SKU catalog-completeness report, across SKU kinds.

Unlike audio_shopify_inventory_reconcile.py (availability-based — only shows
*unassigned* cables), this lists EVERY variant that exists in Postgres with its
total count, including variants where every cable is already assigned to a
customer. Those fully-assigned variants are invisible to the reconcile, but you
still need them to exist as Shopify variants — so this is the report you
productize from.

Pick which SKU kinds to include:
    --std        standard catalog SKUs        (group SKU like 'GL', 'SL', ...)
    --ltd        limited editions             (group SKU like 'LTD-...')
    --misc       special babies (custom/MISC) (group SKU like 'SC-MISC-42')
With no kind flag, all three are included. For --std, every length/connector
the catalog config defines is shown even when Postgres has none of them, so
you see full catalog coverage (0-count rows flag lengths you've never built).

For each variant it shows total / available / assigned / wholesale counts and
whether a matching variant SKU exists in Shopify (✓ / ✗ CREATE / ? if the
Shopify fetch failed). It also flags, per included kind:
  - variants in Postgres with NO Shopify variant   (need to create)
  - Shopify variants with a blank/null SKU          (need to fill the SKU in)
  - Shopify variants of that kind with NO PG cables (phantom / never built)

Usage:
    python util/audio/audio_sku_catalog_report.py                 # all kinds
    python util/audio/audio_sku_catalog_report.py --ltd           # editions only
    python util/audio/audio_sku_catalog_report.py --ltd --misc    # editions + specials
    python util/audio/audio_sku_catalog_report.py --group LTD-GREENRIVER2026
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from greenlight.log import setup_logging
setup_logging()

from greenlight.db import pg_pool
from greenlight.cable_config import (
    format_variant_sku, parse_group_sku, parse_variant_sku,
    all_patterns, all_prefixes, series_data_for_prefix,
)
from greenlight.shopify_client import get_all_product_skus, get_all_products

# Display metadata per kind, in report order.
KIND_LABELS = {
    "catalog": "STANDARD CATALOG",
    "ltd": "LIMITED EDITIONS",
    "misc": "SPECIAL BABIES (MISC)",
}
KIND_ORDER = ["catalog", "ltd", "misc"]


def expected_catalog_variants(group=None):
    """Full standard-catalog matrix from config: {pattern_code: {variant_sku}}.

    A pattern (patterns.yaml) is offered by every series (cable_lines.yaml)
    whose braid_material matches the pattern's fabric_type, at each of that
    series' lengths × connectors. This is the *complete* expected set, so the
    report can show every length even when Postgres holds none of them.
    """
    expected = {}
    for pat in all_patterns():
        code = pat.get("code")
        if group and group != code:
            continue
        fabric = (pat.get("fabric_type") or "").lower()
        for prefix in all_prefixes():
            s = series_data_for_prefix(prefix) or {}
            if (s.get("braid_material") or "").lower() != fabric:
                continue
            for length in s.get("lengths", []):
                for conn in s.get("connectors", []):
                    cc = conn.get("code") or ""
                    vsku = format_variant_sku(
                        group_sku=code, prefix=prefix, length=length, connector_code=cc,
                    )
                    if vsku:
                        expected.setdefault(code, set()).add(vsku)
    return expected


def get_variant_counts(kinds, group=None):
    """Return {kind: {sku_group: {variant_sku: {total, available, assigned, wholesale}}}}.

    Availability mirrors db.get_available_count_for_sku so this agrees with the
    reconcile: available = passed QC, unassigned, not wholesale.
    """
    where = "TRUE"
    params = []
    if group:
        where += " AND sku_group = %s"
        params.append(group)

    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT sku_group, prefix, length, connector_code,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (
                           WHERE test_passed
                             AND registration_code IS NULL
                             AND (shopify_gid IS NULL OR shopify_gid = '')
                       ) AS available,
                       COUNT(*) FILTER (
                           WHERE shopify_gid IS NOT NULL AND shopify_gid <> ''
                       ) AS assigned,
                       COUNT(*) FILTER (
                           WHERE registration_code IS NOT NULL
                       ) AS wholesale
                FROM audio_cables
                WHERE {where}
                GROUP BY sku_group, prefix, length, connector_code
                ORDER BY sku_group, prefix, length, connector_code
            """, params or None)

            out = {}
            for sku_group, prefix, length, cc, total, avail, assigned, whol in cur.fetchall():
                kind = parse_group_sku(sku_group).get("kind")
                if kind not in kinds:
                    continue
                length_val = float(length) if length is not None else None
                if length_val is not None and length_val.is_integer():
                    length_val = int(length_val)
                variant_sku = format_variant_sku(
                    group_sku=sku_group, prefix=prefix,
                    length=length_val, connector_code=cc,
                )
                if not variant_sku:
                    variant_sku = f"<unresolved {prefix}/{length_val}/{cc!r}>"
                slot = out.setdefault(kind, {}).setdefault(sku_group, {}).setdefault(
                    variant_sku, {"total": 0, "available": 0, "assigned": 0, "wholesale": 0}
                )
                slot["total"] += total
                slot["available"] += avail
                slot["assigned"] += assigned
                slot["wholesale"] += whol

            # Standard catalog: overlay the full expected matrix so every
            # length/connector shows up (0-filled) even with no cables in PG.
            if "catalog" in kinds:
                for pattern_code, variant_skus in expected_catalog_variants(group).items():
                    grp = out.setdefault("catalog", {}).setdefault(pattern_code, {})
                    for vsku in variant_skus:
                        grp.setdefault(
                            vsku,
                            {"total": 0, "available": 0, "assigned": 0, "wholesale": 0},
                        )
            return out
    finally:
        pg_pool.putconn(conn)


def get_shopify_info():
    """Return (skus_by_kind, blank_variants).

    skus_by_kind: {kind: set(variant_sku)} for every Shopify variant SKU.
    blank_variants: [(product_title, variant_title)] for variants with no SKU.
    """
    shopify_skus = get_all_product_skus()
    skus_by_kind = {"catalog": set(), "ltd": set(), "misc": set()}
    for sku in shopify_skus:
        k = parse_variant_sku(sku).get("kind")
        if k in skus_by_kind:
            skus_by_kind[k].add(sku)

    blank = []
    for product in get_all_products():
        title = product.get("title")
        for v in product.get("variants", {}).get("edges", []):
            node = v["node"]
            if not (node.get("sku") or "").strip():
                blank.append((title, node.get("title")))
    return skus_by_kind, blank


def print_report(kinds, group=None):
    print("Fetching Postgres variant counts...")
    by_kind = get_variant_counts(kinds, group)

    print("Fetching Shopify variants...")
    try:
        shopify_by_kind, blank_variants = get_shopify_info()
        shopify_ok = True
    except Exception as e:
        print(f"  (Shopify fetch failed: {e} — showing counts only)")
        shopify_by_kind, blank_variants, shopify_ok = {}, [], False

    if not by_kind:
        print("No matching cables found in Postgres.")
        return

    print(f"\n{'='*74}")
    print("SKU CATALOG REPORT")
    print(f"{'='*74}")

    missing_by_kind = {}
    pg_skus_by_kind = {}

    for kind in KIND_ORDER:
        if kind not in kinds or kind not in by_kind:
            continue
        groups = by_kind[kind]
        n_cables = sum(c["total"] for g in groups.values() for c in g.values())
        print(f"\n### {KIND_LABELS[kind]}  ({n_cables} cables, {len(groups)} groups) ###")

        pg_skus_by_kind[kind] = set()
        missing_by_kind[kind] = []

        for sku_group in sorted(groups):
            variants = groups[sku_group]
            g_total = sum(c["total"] for c in variants.values())
            print(f"\n  {sku_group}  ({g_total} cables)")
            print(f"    {'variant SKU':<34}{'total':>6}{'avail':>6}{'assign':>7}{'whol':>5}   Shopify")
            print(f"    {'-'*70}")
            for variant_sku in sorted(variants):
                c = variants[variant_sku]
                pg_skus_by_kind[kind].add(variant_sku)
                if not shopify_ok:
                    mark = "?"
                elif variant_sku in shopify_by_kind.get(kind, set()):
                    mark = "✓"
                else:
                    mark = "✗ CREATE"
                    missing_by_kind[kind].append(variant_sku)
                print(f"    {variant_sku:<34}{c['total']:>6}{c['available']:>6}"
                      f"{c['assigned']:>7}{c['wholesale']:>5}   {mark}")

    if not shopify_ok:
        print()
        return

    # ---- cross-reference summaries ----
    print(f"\n{'='*74}\nCROSS-REFERENCE vs SHOPIFY\n{'='*74}")

    any_missing = any(missing_by_kind.get(k) for k in kinds)
    if any_missing and blank_variants:
        print("\n(NOTE: some '✗ CREATE' items may be the blank-SKU variants listed"
              "\n further below — a variant already exists in Shopify, it just needs"
              "\n its SKU filled in. Fill the SKU rather than creating a duplicate.)")
    if any_missing:
        for kind in KIND_ORDER:
            miss = missing_by_kind.get(kind) or []
            if miss:
                print(f"\nIn Postgres but NOT in Shopify — {KIND_LABELS[kind]} ({len(miss)}):")
                for s in miss:
                    print(f"  ✗ {s}")
    else:
        print("\nEvery included Postgres variant has a matching Shopify variant.")

    if blank_variants:
        print(f"\nShopify variants with a BLANK SKU ({len(blank_variants)}) — fill these in:")
        for prod, var in blank_variants:
            print(f"  ⚠ {prod!r} / variant {var!r}")

    # Phantom (in Shopify, no PG cables). Noisy for standard catalog (out-of-
    # stock is normal), so only surface it for ltd / misc.
    for kind in KIND_ORDER:
        if kind == "catalog" or kind not in kinds:
            continue
        phantom = sorted(shopify_by_kind.get(kind, set()) - pg_skus_by_kind.get(kind, set()))
        if phantom:
            print(f"\nIn Shopify but NO Postgres cables — {KIND_LABELS[kind]} ({len(phantom)}):")
            for s in phantom:
                print(f"  • {s}")

    print()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--std", action="store_true",
                        help="Include standard catalog SKUs (shows all expected lengths)")
    parser.add_argument("--ltd", action="store_true", help="Include limited editions")
    parser.add_argument("--misc", action="store_true", help="Include special babies (MISC)")
    parser.add_argument("--group", help="Limit to one sku_group, e.g. LTD-GREENRIVER2026")
    args = parser.parse_args()

    kinds = set()
    if args.std:
        kinds.add("catalog")
    if args.ltd:
        kinds.add("ltd")
    if args.misc:
        kinds.add("misc")
    if not kinds:  # no flag → all kinds
        kinds = {"catalog", "ltd", "misc"}

    print_report(kinds, args.group)


if __name__ == "__main__":
    main()
