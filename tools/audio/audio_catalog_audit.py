#!/usr/bin/env python3
"""
Cross-check the audio catalog against Shopify. Read-only; changes nothing.

Run before a wholesale launch, after loading UPCs, and after editing
catalog/. The point is the class of error where two sources agree and are
both wrong: three Electric Houndstooth variants once carried the 10/20 ft
SKUs in Shopify *and* in GS1 Data Hub, so neither contradicted the other.
Only checking each SKU against its own Shopify naming caught it.

Checks
  1. Coverage both ways -- every catalog variant exists in Shopify, and no
     catalog-shaped Shopify SKU is missing from catalog/.
  2. Every catalog variant has a UPC, and every UPC is a valid GTIN-12.
  3. No UPC is shared by two SKUs. A GTIN identifies one trade item; sharing
     one is the single worst thing in this file, because it is invisible at
     the till and permanent once retailers have it.
  4. No MISC or LTD variant carries a UPC -- those are one-offs and limited
     runs, excluded from the retail GTIN range by SKU kind.
  5. Shopify's own naming agrees with each SKU: length, right-angle,
     instrument/microphone, and pattern. This is check 1-of-the-EH-bug.
  6. Prices match catalog/back_office/economics.yaml to the cent.

Usage:
    python tools/audio/audio_catalog_audit.py
    python tools/audio/audio_catalog_audit.py --quiet    # only problems

Exit status is 1 if anything failed, so this can gate a release.

Not checked here: packaged weight (Shopify's bulk SKU fetch doesn't return
it, and it matters for GS1 Data Hub rather than for labels), unit costs
(internal only), inventory counts, and anything on the Data Hub side -- its
API is deferred, see docs/UPC_ROLLOUT_STATUS.md.
"""

import argparse
import os
import re
import sys
from collections import defaultdict
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from greenlight.cable_config import (
    all_patterns, all_series, describe_variant, format_variant_sku,
    parse_variant_sku,
)
from greenlight.gtin import normalize_gtin12, validate_gtin12
from greenlight.product_lines import load_yaml_skus


def catalog_variants() -> set:
    """Every variant SKU the catalog can express.

    A pattern pairs only with a series whose braid matches its fabric_type,
    which is how the real product grid is built.
    """
    skus = set()
    for series in all_series():
        braid = (series.get("braid_material") or "").lower()
        for pattern in all_patterns():
            if pattern.get("fabric_type") != braid:
                continue
            for length in series["lengths"]:
                for conn in series["connectors"]:
                    skus.add(format_variant_sku(
                        group_sku=pattern["code"],
                        prefix=series["sku_prefix"],
                        length=length,
                        connector_code=conn.get("code") or "",
                    ))
    return skus


def audit(rows, problems):
    """Run every check over `rows` (SKU -> Shopify variant), filling problems."""
    catalog = catalog_variants()
    shop_catalog = {s for s in rows
                    if parse_variant_sku(s).get("kind") == "catalog"}

    # 1. coverage, both directions
    for sku in sorted(catalog - shop_catalog):
        problems["catalog variant missing from Shopify"].append(sku)
    for sku in sorted(shop_catalog - catalog):
        problems["Shopify SKU the catalog doesn't know"].append(sku)

    # 2 / 3 / 4. UPCs
    by_upc = defaultdict(list)
    for sku, variant in sorted(rows.items()):
        barcode = (variant.get("barcode") or "").strip()
        kind = parse_variant_sku(sku).get("kind")
        if kind != "catalog":
            if barcode:
                problems["MISC/LTD carrying a UPC"].append(f"{sku} -> {barcode}")
            continue
        if not barcode:
            problems["catalog variant with no UPC"].append(sku)
            continue
        normalized = normalize_gtin12(barcode) or barcode
        ok, err = validate_gtin12(normalized)
        if not ok:
            problems["invalid GTIN-12"].append(f"{sku} -> {barcode} ({err})")
            continue
        by_upc[normalized].append(sku)
    for upc, skus in sorted(by_upc.items()):
        if len(skus) > 1:
            problems["UPC shared by more than one SKU"].append(
                f"{upc}: {', '.join(sorted(skus))}")

    # 5. does Shopify's naming agree with the SKU it hangs on?
    for sku in sorted(shop_catalog & catalog):
        variant, described = rows[sku], describe_variant(sku)
        vtitle = variant.get("variant_title") or ""
        ptitle = variant.get("product_title") or ""

        length = re.match(r"\s*(\d+)\s*'", vtitle)
        if not length:
            problems["variant title states no length"].append(
                f"{sku}: {vtitle!r}")
        elif length.group(1) != described["length"]:
            problems["length disagrees with the SKU"].append(
                f"{sku}: SKU says {described['length']}ft, "
                f"Shopify says {length.group(1)}ft ({vtitle!r})")

        if (described["connector"] == "RA-TS") != ("right angle" in vtitle.lower()):
            problems["right-angle disagrees with the SKU"].append(
                f"{sku}: {vtitle!r}")

        is_mic = described["cable_type"] == "Microphone"
        says_mic = "microphone" in vtitle.lower() or "xlr" in vtitle.lower()
        if is_mic != says_mic:
            problems["instrument/microphone disagrees with the SKU"].append(
                f"{sku}: {vtitle!r}")

        pattern = described["pattern"]
        if pattern and pattern.lower() not in ptitle.lower():
            problems["pattern disagrees with the SKU"].append(
                f"{sku}: SKU says {pattern!r}, title is {ptitle!r}")

    # 6. prices
    lines = load_yaml_skus()
    for sku in sorted(shop_catalog & catalog):
        parsed = parse_variant_sku(sku)
        line = lines.get(parsed["prefix"])
        if not line:
            problems["no economics entry for the series"].append(sku)
            continue
        want = line["pricing"].get(parsed["length"])
        got = rows[sku].get("price")
        if want is None:
            problems["no price in economics.yaml"].append(
                f"{sku} ({parsed['length']}ft)")
        elif got is None:
            problems["no price in Shopify"].append(sku)
        elif Decimal(str(got)) != Decimal(str(want)):
            problems["price disagrees with economics.yaml"].append(
                f"{sku}: yaml ${want} vs Shopify ${got}")

    return len(catalog), len(shop_catalog), len(shop_catalog & catalog)


def main():
    parser = argparse.ArgumentParser(
        description="Cross-check the audio catalog against Shopify.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--quiet", action="store_true",
                        help="Print only problems")
    parser.add_argument("--limit", type=int, default=12,
                        help="Examples shown per problem (default 12)")
    args = parser.parse_args()

    from greenlight.shopify_client import get_all_product_skus
    rows = get_all_product_skus()
    if not rows:
        print("\n  Could not read any SKUs from Shopify. Check credentials "
              "and connectivity.\n")
        return 1

    problems = defaultdict(list)
    n_catalog, n_shop, n_both = audit(rows, problems)

    if not args.quiet:
        print()
        print(f"  Shopify SKUs           {len(rows)}")
        print(f"  catalog variants       {n_catalog}")
        print(f"  catalog-shaped in both {n_both}")
        print(f"  MISC/LTD in Shopify    {len(rows) - n_shop}")
        print()

    if not problems:
        if not args.quiet:
            print("  All checks passed.\n")
        return 0

    total = sum(len(v) for v in problems.values())
    print(f"  {total} problem(s) in {len(problems)} categor"
          f"{'y' if len(problems) == 1 else 'ies'}:\n")
    for name, items in sorted(problems.items()):
        print(f"  !! {name}  ({len(items)})")
        for item in items[:args.limit]:
            print(f"       {item}")
        if len(items) > args.limit:
            print(f"       ... and {len(items) - args.limit} more")
        print()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
