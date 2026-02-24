#!/usr/bin/env python3
"""
Inventory overview and production suggestions.

Shows current stock levels across all SKUs, identifies gaps,
and suggests what to produce next based on coverage and sales history.

Usage:
    python util/inventory_overview.py                # Full overview
    python util/inventory_overview.py --suggest      # Production suggestions only
    python util/inventory_overview.py --series SC    # Filter by SKU prefix
    python util/inventory_overview.py --heatmap      # Length x pattern grid
"""

import sys
import argparse
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from greenlight.db import (
    get_sku_stock_summary as get_sku_counts,
    get_recent_sales,
    get_special_baby_summary,
)
from greenlight.product_lines import (
    PREFIX_MAP, LOW_STOCK_THRESHOLD,
    load_yaml_skus, build_sku, get_cost as _get_cost,
)


def print_overview(series_filter=None):
    """Print full inventory overview."""
    yaml_lines = load_yaml_skus()
    sku_counts = get_sku_counts()
    recent = get_recent_sales(days=90)

    for prefix in sorted(yaml_lines.keys()):
        if series_filter and prefix != series_filter.upper():
            continue

        line = yaml_lines[prefix]
        name = line["name"]

        print(f"\n{'=' * 70}")
        print(f"  {name} ({prefix})")
        print(f"{'=' * 70}")

        # Column headers
        print(f"\n  {'SKU':<20} {'Avail':>6} {'Sold':>6} {'Fail':>6} {'Total':>6}  {'90d Sales':>9}")
        print(f"  {'-' * 62}")

        series_avail = 0
        series_sold = 0
        series_total = 0
        series_failed = 0

        for length in line["lengths"]:
            for pattern in line["patterns"]:
                for conn in line["connectors"]:
                    sku = build_sku(prefix, length, pattern["code"], conn["code"])
                    c = sku_counts.get(sku, {"total": 0, "available": 0, "sold": 0, "failed": 0, "untested": 0})
                    r = recent.get(sku, 0)

                    series_avail += c["available"]
                    series_sold += c["sold"]
                    series_total += c["total"]
                    series_failed += c["failed"]

                    # Highlight out-of-stock SKUs that have sales history
                    flag = ""
                    if c["available"] == 0 and c["sold"] > 0:
                        flag = " << OUT"
                    elif c["available"] <= LOW_STOCK_THRESHOLD and c["available"] > 0 and c["sold"] > 0:
                        flag = " < LOW"

                    avail_str = str(c["available"]) if c["total"] > 0 else "-"
                    sold_str = str(c["sold"]) if c["sold"] > 0 else "-"
                    fail_str = str(c["failed"]) if c["failed"] > 0 else "-"
                    total_str = str(c["total"]) if c["total"] > 0 else "-"
                    recent_str = str(r) if r > 0 else "-"

                    print(f"  {sku:<20} {avail_str:>6} {sold_str:>6} {fail_str:>6} {total_str:>6}  {recent_str:>9}{flag}")

        print(f"  {'-' * 62}")
        print(f"  {'TOTAL':<20} {series_avail:>6} {series_sold:>6} {series_failed:>6} {series_total:>6}")

    # Special babies summary
    misc = get_special_baby_summary()
    if misc and not series_filter:
        print(f"\n{'=' * 70}")
        print(f"  Special Baby (MISC)")
        print(f"{'=' * 70}")
        print(f"\n  {'Series':<20} {'Avail':>6} {'Sold':>6} {'Total':>6}")
        print(f"  {'-' * 42}")
        for series, c in sorted(misc.items()):
            print(f"  {series:<20} {c['available']:>6} {c['sold']:>6} {c['total']:>6}")

    print()


def print_heatmap(series_filter=None):
    """Print a length x pattern heatmap showing available stock."""
    yaml_lines = load_yaml_skus()
    sku_counts = get_sku_counts()

    for prefix in sorted(yaml_lines.keys()):
        if series_filter and prefix != series_filter.upper():
            continue

        line = yaml_lines[prefix]
        name = line["name"]
        patterns = line["patterns"]
        lengths = line["lengths"]

        for conn in line["connectors"]:
            conn_label = conn["display"] if conn["display"] else ""
            title = f"{name}"
            if conn_label:
                title += f" ({conn_label})"

            print(f"\n{title}")
            print(f"Available stock by length x pattern:\n")

            # Header row
            pat_codes = [p["code"] for p in patterns]
            header = f"  {'Length':>6}"
            for code in pat_codes:
                header += f"  {code:>4}"
            header += f"  {'TOTAL':>6}"
            print(header)
            print(f"  {'-' * (8 + 6 * len(pat_codes) + 8)}")

            col_totals = defaultdict(int)
            for length in lengths:
                row = f"  {str(length) + 'ft':>6}"
                row_total = 0
                for pattern in patterns:
                    sku = build_sku(prefix, length, pattern["code"], conn["code"])
                    c = sku_counts.get(sku, {"available": 0})
                    avail = c["available"]
                    row_total += avail
                    col_totals[pattern["code"]] += avail

                    if avail == 0:
                        row += f"  {'·':>4}"
                    else:
                        row += f"  {avail:>4}"
                row += f"  {row_total:>6}"
                print(row)

            # Footer totals
            footer = f"  {'TOTAL':>6}"
            grand = 0
            for code in pat_codes:
                footer += f"  {col_totals[code]:>4}"
                grand += col_totals[code]
            footer += f"  {grand:>6}"
            print(f"  {'-' * (8 + 6 * len(pat_codes) + 8)}")
            print(footer)

    print()


def print_suggestions(series_filter=None):
    """Print production suggestions ranked by priority."""
    yaml_lines = load_yaml_skus()
    sku_counts = get_sku_counts()
    recent_90 = get_recent_sales(days=90)
    recent_30 = get_recent_sales(days=30)

    suggestions = []

    for prefix in sorted(yaml_lines.keys()):
        if series_filter and prefix != series_filter.upper():
            continue

        line = yaml_lines[prefix]
        for length in line["lengths"]:
            for pattern in line["patterns"]:
                for conn in line["connectors"]:
                    sku = build_sku(prefix, length, pattern["code"], conn["code"])
                    c = sku_counts.get(sku, {"total": 0, "available": 0, "sold": 0, "failed": 0})
                    avail = c["available"]
                    sold = c["sold"]
                    sales_90 = recent_90.get(sku, 0)
                    sales_30 = recent_30.get(sku, 0)
                    cost = _get_cost(line, length, conn["code"])
                    price = line["pricing"].get(length, 0)

                    # Skip SKUs with healthy stock
                    if avail > LOW_STOCK_THRESHOLD:
                        continue

                    # Calculate priority score
                    # Higher = more urgent to produce
                    score = 0
                    reason = []

                    if avail == 0 and sold > 0:
                        score += 50
                        reason.append(f"out of stock, {sold} sold all-time")
                    elif avail == 0 and sold == 0:
                        score += 5
                        reason.append("never produced")
                    elif avail > 0:
                        score += 20
                        reason.append(f"low stock ({avail} left)")

                    if sales_30 > 0:
                        score += sales_30 * 15
                        reason.append(f"{sales_30} sold last 30d")
                    elif sales_90 > 0:
                        score += sales_90 * 5
                        reason.append(f"{sales_90} sold last 90d")

                    # Margin boost: prioritize higher-margin SKUs slightly
                    if price and cost:
                        margin = price - cost
                        score += margin * 0.1

                    suggestions.append({
                        "sku": sku,
                        "series": PREFIX_MAP.get(prefix, prefix),
                        "available": avail,
                        "sold": sold,
                        "sales_90": sales_90,
                        "score": score,
                        "reasons": reason,
                        "price": price,
                        "cost": cost,
                    })

    # Sort by score descending
    suggestions.sort(key=lambda x: x["score"], reverse=True)

    # Split into tiers
    high = [s for s in suggestions if s["score"] >= 50]
    medium = [s for s in suggestions if 15 <= s["score"] < 50]
    low = [s for s in suggestions if 5 <= s["score"] < 15]
    never = [s for s in suggestions if s["score"] < 5]

    print(f"\n{'=' * 70}")
    print("  PRODUCTION SUGGESTIONS")
    print(f"{'=' * 70}")

    if high:
        print(f"\n  HIGH PRIORITY — out of stock with sales history")
        print(f"  {'-' * 65}")
        _print_suggestion_rows(high)

    if medium:
        print(f"\n  MEDIUM — low stock or recent sales")
        print(f"  {'-' * 65}")
        _print_suggestion_rows(medium)

    if low:
        print(f"\n  LOW — some historical sales but no recent demand")
        print(f"  {'-' * 65}")
        _print_suggestion_rows(low)

    # Only show "never produced" if specifically requested or few suggestions
    if never and (len(high) + len(medium) + len(low) < 5):
        print(f"\n  COVERAGE GAPS — defined but never produced")
        print(f"  {'-' * 65}")
        for s in never[:20]:
            margin_str = ""
            if s["price"] and s["cost"]:
                margin_str = f"  margin ${s['price'] - s['cost']:.0f}"
            print(f"    {s['sku']:<20} {', '.join(s['reasons'])}{margin_str}")

    total = len(high) + len(medium) + len(low)
    print(f"\n  {total} SKUs need attention ({len(high)} high, {len(medium)} medium, {len(low)} low)")
    if never:
        print(f"  {len(never)} SKUs defined but never produced")
    print()


def _print_suggestion_rows(items):
    """Print formatted suggestion rows."""
    for s in items:
        margin_str = ""
        if s["price"] and s["cost"]:
            margin_str = f"${s['price'] - s['cost']:.0f} margin"
        print(f"    {s['sku']:<20} avail={s['available']}  sold={s['sold']:<4}  "
              f"90d={s['sales_90']:<3}  {margin_str}")
        if s["reasons"]:
            print(f"    {'':20} {', '.join(s['reasons'])}")


def main():
    parser = argparse.ArgumentParser(
        description="Inventory overview and production suggestions"
    )
    parser.add_argument("--series", type=str, default=None,
                        help="Filter by SKU prefix (SC, SV, TC, TV)")
    parser.add_argument("--suggest", action="store_true",
                        help="Show production suggestions only")
    parser.add_argument("--heatmap", action="store_true",
                        help="Show length x pattern availability grid")
    args = parser.parse_args()

    if args.suggest:
        print_suggestions(args.series)
    elif args.heatmap:
        print_heatmap(args.series)
    else:
        print_overview(args.series)
        print_heatmap(args.series)
        print_suggestions(args.series)


if __name__ == "__main__":
    main()
