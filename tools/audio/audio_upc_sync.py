#!/usr/bin/env python3
"""Load retail UPCs (GTIN-12) from a CSV onto Shopify audio cable variants.

Shopify's variant `barcode` field is the source of truth for UPCs — there is
deliberately no UPC column in Postgres. This script is the one-way loader:
GS1 Data Hub export (or any CSV) -> Shopify.

The CSV needs a SKU column and a UPC column; everything else is ignored, so a
Data Hub export can be fed in unmodified. Recognized headers (case- and
space-insensitive):
    SKU:  sku, variant_sku, internal part number or sku
    UPC:  upc, gtin, barcode, gtin12
Data Hub's 14-digit GTINs (00 + UPC-A) are normalized to the 12-digit UPC.

Runs as a dry run by default and prints exactly what it would change. Nothing
is written to Shopify without --fix.

Safety checks, all of which run before any write:
  - every UPC is a well-formed GTIN-12 with a correct check digit
  - no UPC appears twice in the CSV (two variants sharing a GTIN is the single
    most expensive mistake available here)
  - no SKU appears twice in the CSV
  - every SKU exists as a variant in the audio Shopify store
  - no UPC is already assigned to a *different* SKU in Shopify
  - a variant that already has a different UPC is reported and skipped, never
    overwritten; a GTIN assignment is permanent

Usage:
    python tools/audio/audio_upc_sync.py upcs.csv              # dry run
    python tools/audio/audio_upc_sync.py upcs.csv --fix        # apply
    python tools/audio/audio_upc_sync.py --coverage            # who's missing a UPC
"""

import sys
import csv
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from greenlight.log import setup_logging
setup_logging()

from greenlight.cable_config import parse_variant_sku
from greenlight.gtin import validate_gtin12, normalize_gtin12
from greenlight.shopify_client import get_all_product_skus, set_barcode_for_sku

SKU_HEADERS = ("sku", "variantsku", "internalpartnumberorsku")
UPC_HEADERS = ("upc", "gtin", "barcode", "gtin12")


def _is_retail(sku):
    """Catalog variants carry retail UPCs. MISC ("Special Baby") one-offs and
    LTD editions are not retail-boxed, so coverage reporting skips them rather
    than flagging them as gaps. Keyed off the SKU, not Shopify's product type,
    which is free text ("Studio Series", "Touring Series", ...)."""
    return parse_variant_sku(sku).get("kind") == "catalog"


def _norm_header(h):
    return "".join((h or "").lower().split()).replace("_", "").replace("-", "")


def read_csv(path):
    """Parse the CSV into [(row_number, sku, raw_upc)].

    Exits with a clear message if the required columns aren't present.
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            sys.exit(f"Error: {path} is empty")

        norm = [_norm_header(h) for h in header]
        sku_idx = next((i for i, h in enumerate(norm) if h in SKU_HEADERS), None)
        upc_idx = next((i for i, h in enumerate(norm) if h in UPC_HEADERS), None)

        if sku_idx is None or upc_idx is None:
            sys.exit(
                f"Error: {path} needs a SKU column ({'/'.join(SKU_HEADERS)}) "
                f"and a UPC column ({'/'.join(UPC_HEADERS)}).\n"
                f"       Found columns: {', '.join(header)}"
            )

        rows = []
        for n, row in enumerate(reader, start=2):
            if len(row) <= max(sku_idx, upc_idx):
                continue
            sku = row[sku_idx].strip()
            upc = row[upc_idx].strip()
            if not sku and not upc:
                continue
            rows.append((n, sku, upc))
        return rows


def validate_rows(rows):
    """Validate and normalize CSV rows.

    Returns (clean, errors) where clean is [(sku, upc)] with canonical 12-digit
    UPCs and errors is a list of human-readable problem strings.
    """
    clean = []
    errors = []
    seen_sku = {}
    seen_upc = {}

    for n, sku, raw_upc in rows:
        if not sku:
            errors.append(f"row {n}: UPC {raw_upc} has no SKU")
            continue
        if not raw_upc:
            errors.append(f"row {n}: {sku} has no UPC")
            continue

        upc = normalize_gtin12(raw_upc)
        if not upc:
            _, why = validate_gtin12(raw_upc)
            errors.append(f"row {n}: {sku} — {why}")
            continue

        if sku in seen_sku:
            errors.append(
                f"row {n}: {sku} appears twice (also row {seen_sku[sku]})")
            continue
        if upc in seen_upc:
            errors.append(
                f"row {n}: UPC {upc} already used by "
                f"{seen_upc[upc][0]} on row {seen_upc[upc][1]} — a GTIN "
                f"identifies exactly one trade item")
            continue

        seen_sku[sku] = n
        seen_upc[upc] = (sku, n)
        clean.append((sku, upc))

    return clean, errors


def plan(clean, shopify_map):
    """Diff the CSV against Shopify.

    Returns (to_write, already_set, problems).
    """
    # Reverse index of UPCs already live in Shopify, to catch a CSV row that
    # would hand an existing GTIN to a second SKU.
    upc_owner = {}
    for sku, info in shopify_map.items():
        if info.get("barcode"):
            upc_owner[info["barcode"]] = sku

    to_write, already_set, problems = [], [], []

    for sku, upc in clean:
        info = shopify_map.get(sku)
        if not info:
            problems.append(f"{sku}: no such variant in the audio Shopify store")
            continue

        existing = info.get("barcode")
        if existing == upc:
            already_set.append((sku, upc))
            continue
        if existing:
            problems.append(
                f"{sku}: already has UPC {existing}, CSV says {upc} — "
                f"refusing to overwrite")
            continue

        owner = upc_owner.get(upc)
        if owner and owner != sku:
            problems.append(
                f"{sku}: UPC {upc} is already assigned to {owner} in Shopify")
            continue

        to_write.append((sku, upc, info.get("product_title") or ""))

    return to_write, already_set, problems


def show_coverage(shopify_map):
    """List retail variants with and without a UPC."""
    retail = {
        sku: info for sku, info in shopify_map.items()
        if _is_retail(sku)
    }
    with_upc = {s: i for s, i in retail.items() if i.get("barcode")}
    without = sorted(s for s in retail if s not in with_upc)

    print(f"Retail (catalog) variants: {len(retail)}")
    print(f"  with a UPC:    {len(with_upc)}")
    print(f"  missing a UPC: {len(without)}")
    if without:
        print()
        for sku in without:
            print(f"    {sku:16} {retail[sku].get('product_title', '')}")

    other = len(shopify_map) - len(retail)
    if other:
        print()
        print(f"  ({other} non-retail variants — MISC/LTD one-offs — not counted)")
    return len(without)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("csv_path", nargs="?",
                        help="CSV with SKU and UPC columns")
    parser.add_argument("--fix", action="store_true",
                        help="Apply the changes (default is a dry run)")
    parser.add_argument("--coverage", action="store_true",
                        help="Report which retail variants have no UPC yet")
    args = parser.parse_args()

    if not args.csv_path and not args.coverage:
        parser.print_help()
        return 1

    print("Fetching variants from the audio Shopify store...")
    shopify_map = get_all_product_skus()
    if not shopify_map:
        print("  Could not fetch Shopify variants (see log). Aborting.")
        return 1
    print(f"  {len(shopify_map)} variants")
    print()

    if args.coverage and not args.csv_path:
        show_coverage(shopify_map)
        return 0

    rows = read_csv(args.csv_path)
    print(f"Read {len(rows)} row(s) from {args.csv_path}")

    clean, errors = validate_rows(rows)
    to_write, already_set, problems = plan(clean, shopify_map)

    if errors:
        print()
        print(f"CSV errors ({len(errors)}) — these rows were skipped:")
        for e in errors:
            print(f"  ✗ {e}")

    if problems:
        print()
        print(f"Shopify conflicts ({len(problems)}) — these were skipped:")
        for p in problems:
            print(f"  ✗ {p}")

    if already_set:
        print()
        print(f"Already correct ({len(already_set)}):")
        for sku, upc in already_set:
            print(f"  = {sku:16} {upc}")

    print()
    if not to_write:
        print("Nothing to write.")
    else:
        print(f"To write ({len(to_write)}):")
        for sku, upc, title in to_write:
            print(f"  + {sku:16} {upc}  {title}")

    # Any validation error or conflict means the input is not yet trustworthy.
    # Refuse to write a partial batch — fix the CSV and re-run.
    blocked = bool(errors or problems)

    if not args.fix:
        print()
        if to_write and not blocked:
            print(f"Dry run. Re-run with --fix to write {len(to_write)} UPC(s).")
        elif blocked:
            print("Dry run. Resolve the errors above before using --fix.")
        return 0

    if blocked:
        print()
        print("Refusing to write: resolve the errors above first. "
              "A partial UPC load is harder to audit than none.")
        return 1

    if not to_write:
        return 0

    print()
    confirm = input(f"Write {len(to_write)} UPC(s) to Shopify? (yes/no): ")
    if confirm.strip().lower() != "yes":
        print("Cancelled")
        return 0

    print()
    ok_count = 0
    for sku, upc, _ in to_write:
        success, err = set_barcode_for_sku(sku, upc)
        if success:
            ok_count += 1
            print(f"  ✓ {sku:16} {upc}")
        else:
            print(f"  ✗ {sku:16} {err}")

    print()
    print(f"Wrote {ok_count} of {len(to_write)} UPC(s)")
    return 0 if ok_count == len(to_write) else 1


if __name__ == "__main__":
    sys.exit(main() or 0)
