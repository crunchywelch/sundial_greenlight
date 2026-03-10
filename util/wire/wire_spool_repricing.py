#!/usr/bin/env python3
"""Generate wire spool repricing analysis CSV.

Compares current spool pricing against by-the-foot prices,
applies proposed discount tiers, and calculates margin impact.

Usage:
    python -m util.wire.wire_spool_repricing
"""

import sqlite3
import re
import csv
from collections import defaultdict
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "sundial.db"
COST_AUDIT_PATH = Path(__file__).parent.parent.parent / "data" / "exports" / "wire_cost_audit.csv"
OUTPUT_PATH = Path(__file__).parent.parent.parent / "data" / "exports" / "wire_spool_repricing.csv"

# Service SKUs to exclude
EXCLUDE_SKUS = {"WIRECHNG", "WCUTMX18MX10"}

# Proposed discount tiers by spool footage
PROPOSED_DISCOUNT = {
    50: 0.10,
    100: 0.175,
    250: 0.325,
    500: 0.40,
}

FIELDS = [
    "sku", "series", "title", "option", "non_ul", "feet", "qty_on_hand",
    "cost", "cost_per_foot", "foot_price", "full_price_equiv",
    "current_price", "current_margin_pct", "current_discount_pct",
    "proposed_discount_pct", "proposed_price", "per_foot_proposed",
    "proposed_margin_pct", "price_change",
]


def get_feet(option):
    if not option:
        return 1
    option = option.lower()
    if "by the foot" in option:
        return 1
    m = re.search(r"(\d+)-foot", option)
    if m:
        return int(m.group(1))
    if option == "default title":
        return 1
    return 1


def is_non_ul(option):
    if not option:
        return False
    return "non ul" in option.lower() or "non-ul" in option.lower()


def load_costs():
    costs = {}
    with open(COST_AUDIT_PATH) as f:
        for row in csv.DictReader(f):
            sku = row["SKU"].strip()
            try:
                costs[sku] = float(row["Cost"])
            except (ValueError, KeyError):
                pass
    return costs


def main():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    cost_lookup = load_costs()

    rows = db.execute("""
        SELECT sku, handle, title, option, price, qty
        FROM products
        WHERE is_wire = 1 AND sku LIKE 'W%'
        ORDER BY handle, sku
    """).fetchall()

    families = defaultdict(list)
    for r in rows:
        d = dict(r)
        if d["sku"] in EXCLUDE_SKUS:
            continue
        d["feet"] = get_feet(d["option"])
        d["non_ul"] = is_non_ul(d["option"])
        d["cost"] = cost_lookup.get(d["sku"])
        families[d["handle"]].append(d)

    # Build foot price lookup with NON-UL -> UL fallback
    foot_prices = {}
    for handle, skus in families.items():
        for s in skus:
            if s["feet"] == 1:
                foot_prices[(handle, s["non_ul"])] = s["price"]

    def get_foot_price(handle, non_ul):
        fp = foot_prices.get((handle, non_ul))
        if fp:
            return fp
        return foot_prices.get((handle, False))

    out_rows = []

    for handle, skus in sorted(families.items()):
        for s in sorted(skus, key=lambda x: (x["non_ul"], x["feet"], x["sku"])):
            feet = s["feet"]
            sku = s["sku"]
            price = s["price"]
            cost = s["cost"]
            foot_price = get_foot_price(handle, s["non_ul"])

            current_margin = ""
            if cost and price and price > 0:
                current_margin = round((1 - cost / price) * 100, 1)

            if feet == 1:
                full_price_equiv = price
                current_discount = 0
                proposed_discount = 0
                proposed_price = price
                per_foot_proposed = price
                change = 0
                proposed_margin = current_margin
            elif foot_price and foot_price > 0:
                full_price_equiv = foot_price * feet
                current_discount = (1 - price / full_price_equiv) if full_price_equiv > 0 else 0
                proposed_discount = PROPOSED_DISCOUNT.get(feet, 0)
                proposed_price = round(full_price_equiv * (1 - proposed_discount), 2)
                per_foot_proposed = proposed_price / feet if feet > 0 else 0
                change = proposed_price - price
                proposed_margin = ""
                if cost and proposed_price and proposed_price > 0:
                    proposed_margin = round((1 - cost / proposed_price) * 100, 1)
            else:
                full_price_equiv = None
                current_discount = None
                proposed_discount = PROPOSED_DISCOUNT.get(feet, 0)
                proposed_price = None
                per_foot_proposed = None
                change = None
                proposed_margin = ""

            series = sku[:4] if len(sku) >= 4 else sku

            out_rows.append({
                "sku": sku,
                "series": series,
                "title": s["title"],
                "option": s["option"],
                "non_ul": "Y" if s["non_ul"] else "",
                "feet": feet,
                "qty_on_hand": s["qty"] or 0,
                "cost": round(cost, 2) if cost else "",
                "cost_per_foot": round(cost / feet, 4) if cost and feet else "",
                "foot_price": foot_price if foot_price else "",
                "full_price_equiv": round(full_price_equiv, 2) if full_price_equiv else "",
                "current_price": price,
                "current_margin_pct": current_margin,
                "current_discount_pct": round(current_discount * 100, 1) if current_discount is not None else "",
                "proposed_discount_pct": round(proposed_discount * 100, 1),
                "proposed_price": proposed_price if proposed_price else "",
                "per_foot_proposed": round(per_foot_proposed, 4) if per_foot_proposed else "",
                "proposed_margin_pct": proposed_margin,
                "price_change": round(change, 2) if change is not None else "",
            })

    with open(OUTPUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)

    missing = [r for r in out_rows if r["foot_price"] == "" and r["feet"] > 1]
    print(f"Wrote {len(out_rows)} rows to {OUTPUT_PATH}")
    print(f"SKUs missing foot_price: {len(missing)}")

    db.close()


if __name__ == "__main__":
    main()
