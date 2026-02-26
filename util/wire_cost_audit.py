#!/usr/bin/env python3
"""
Audit wire SKU costs in the inventory worksheet against formula calculations.

Reads wire_cost_data.yaml for raw cost inputs, decodes each W-prefix SKU
from the inventory CSV, calculates expected cost using the formula:

    ROUND((sum(WIRECOST, YARNCOST) * QTY) + SPOOLCOST, 2)

and flags any discrepancies.

Usage:
    python util/wire_cost_audit.py             # Show mismatches only
    python util/wire_cost_audit.py --all       # Show all SKUs
    python util/wire_cost_audit.py --pattern W182CT  # Filter to pattern
"""

import csv
import re
import sys
import argparse
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import yaml

YAML_PATH = Path(__file__).parent.parent / "docs" / "wire_cost_data.yaml"
CSV_PATH = Path(__file__).parent.parent / "docs" / "wire_inventory_worksheet_2-4-2026.csv"

# Wire conductor cost per foot for each SKU pattern (family + braid + style).
# Values from wire_cost_data.yaml wire_costs and lamp_cordPricing-skus.csv.
WIRE_COST_PER_FT = {
    "W121CR": 0.95286,   # 12/1 lacquered
    "W141CR": 0.07995,   # 14/1 AWM 1015 (estimate)
    "W143CP": 0.31430,   # 14/3 SJT
    "W143RP": 0.31430,   # 14/3 SJT
    "W162CT": 0.15990,   # 16/1 AWM 1015 + Stripe
    "W163CJ": 0.31430,   # 16/3 SJT-B (estimate, using 14/3 SJT)
    "W163CS": 0.45154,   # 16awg 3 conductor twisted (overbraid)
    "W181CR": 0.05475,   # 18/1 AWM 1015
    "W181RR": 0.05475,   # 18/1 AWM 1015
    "W182CT": 0.10950,   # 18/1 AWM 1015 + Stripe
    "W182RT": 0.10950,   # 18/1 AWM 1015 + Stripe
    "W182CF": 0.13015,   # 18/2 SPT-1
    "W182RF": 0.13015,   # 18/2 SPT-1
    "W182CP": 0.10412,   # 18/2 SVT
    "W182RP": 0.10412,   # 18/2 SVT
    "W183CP": 0.26197,   # 18/3 SVT-3
    "W183RP": 0.26197,   # 18/3 SVT-3
    "W183CJ": 0.31430,   # 18/3 SJT (estimate, using 14/3 SJT)
    "W202CT": 0.06714,   # 20/1 AWM 1015 + Stripe (estimate)
    "W202RT": 0.06714,   # 20/1 AWM 1015 + Stripe (estimate)
    "W222CT": 0.06714,   # 22/1 AWM 1015 + Stripe
    "W222RT": 0.06714,   # 22/1 AWM 1015 + Stripe
}

# Yarn usage rate (lbs per 100 feet) by wire family and style.
# From wire_cost_data.yaml yarn_per_100ft.
YARN_PER_100FT = {
    "W121": 0,
    "W141": 0.20,
    "W143": 0.35,
    "W162": 0.35,
    "W163": 0.35,
    "W181": 0.20,
    "W182T": 0.25,   # twisted
    "W182F": 0.25,   # flat/parallel
    "W182P": 0.35,   # pulley SVT
    "W182J": 0.35,   # heavy SJT
    "W183": 0.35,
    "W202": 0.25,
    "W222": 0.25,
}

# Spool costs by (family/style, qty).
# From lamp_cordPricing-skus.csv spool column.
SPOOL_COSTS = {
    ("W121", 100): 4.75,
    ("W121", 250): 4.75,
    ("W121", 500): 4.75,
    ("W141", 100): 1.35,
    ("W143", 100): 1.53,
    ("W162", 50): 1.35,
    ("W162", 250): 2.75,
    ("W163", 100): 1.53,
    ("W181C", 250): 1.35,
    ("W181R", 100): 1.53,
    ("W182T", 50): 1.35,
    ("W182T", 250): 2.75,
    ("W182F", 250): 1.35,
    ("W182P", 100): 1.53,
    ("W182J", 100): 1.53,
    ("W183", 100): 1.53,
    ("W202", 100): 1.35,
    ("W222", 100): 1.35,
    ("W222", 250): 2.75,
}


def load_yaml_costs():
    """Load yarn costs from the YAML file."""
    with open(YAML_PATH) as f:
        return yaml.safe_load(f)


def load_inventory_skus():
    """Load W-prefix SKUs with costs from inventory CSV."""
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        lines = f.readlines()

    reader = csv.DictReader(lines[1:])  # skip grand-total row
    skus = {}
    for row in reader:
        sku = (row.get("Variant SKU") or "").strip()
        cost_str = (row.get("Cost per item") or "").strip()
        option = (row.get("Option1 Value") or "").strip()
        if not sku.startswith("W") or not cost_str:
            continue
        try:
            skus[sku] = {"cost": float(cost_str), "option": option}
        except ValueError:
            continue
    return skus


def decode_sku(sku):
    """Decode a wire SKU into its components.

    SKU format: W[nn][n][C|R][style][color1][color2][tier]
    """
    if len(sku) < 8:
        return None
    return {
        "family": sku[:4],        # W162, W182, etc.
        "braid": sku[4],          # C=cotton, R=rayon
        "style": sku[5],          # T=twisted, P=pulley, J=SJT, F=flat, S=overbraid
        "color1": sku[6:8],       # BK=black, DB=dark brown, etc.
        "pattern": sku[:6],       # W162CT, W182CP, etc.
    }


def parse_option_qty(option):
    """Extract quantity from the option value string."""
    option_lower = option.lower().strip()
    if "by the foot" in option_lower and "spool" not in option_lower:
        return 1
    m = re.search(r"(\d+)-foot", option_lower)
    if m:
        return int(m.group(1))
    return None


def get_yarn_type(decoded):
    """Determine yarn cost category from decoded SKU."""
    if decoded["family"] == "W121":
        return None  # knob and tube, no yarn
    if decoded["braid"] == "C":
        if decoded["color1"] == "BK":
            return "Cotton, Black"
        return "Cotton, Color"
    elif decoded["braid"] == "R":
        if decoded["style"] in ("P", "J"):
            return "Rayon, 5 ends"
        return "Rayon, 2 ends"
    return None


def get_yarn_per_100ft(decoded):
    """Get yarn usage rate for this SKU's wire family."""
    family = decoded["family"]
    style = decoded["style"]

    # W182 varies by style
    if family == "W182":
        key = f"W182{style}"
        return YARN_PER_100FT.get(key)

    return YARN_PER_100FT.get(family)


def get_spool_cost(decoded, qty):
    """Look up spool cost for this pattern and quantity."""
    if qty == 1:
        return Decimal("0")

    family = decoded["family"]
    style = decoded["style"]
    braid = decoded["braid"]

    # Try specific lookups in order of specificity
    lookups = []
    if family in ("W182",):
        lookups.append((f"W182{style}", qty))
    if family in ("W181",):
        lookups.append((f"W181{braid}", qty))
    lookups.append((family, qty))

    for key in lookups:
        if key in SPOOL_COSTS:
            return Decimal(str(SPOOL_COSTS[key]))

    return None


def calc_cost(wire_per_ft, yarn_per_ft, qty, spool_cost):
    """ROUND((sum(WIRECOST, YARNCOST) * QTY) + SPOOLCOST, 2)"""
    total = (Decimal(str(wire_per_ft)) + Decimal(str(yarn_per_ft))) * qty + spool_cost
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def main():
    parser = argparse.ArgumentParser(description="Audit wire SKU costs")
    parser.add_argument("--all", action="store_true", help="Show all SKUs, not just mismatches")
    parser.add_argument("--pattern", help="Filter to a specific pattern (e.g. W182CT)")
    args = parser.parse_args()

    data = load_yaml_costs()
    yarn_costs = data["yarn_costs"]
    skus = load_inventory_skus()

    matches = []
    mismatches = []
    unknown = []

    for sku in sorted(skus):
        info = skus[sku]
        actual_cost = info["cost"]
        option = info["option"]

        decoded = decode_sku(sku)
        if not decoded:
            unknown.append((sku, option, actual_cost, "SKU too short to decode"))
            continue

        pattern = decoded["pattern"]
        if args.pattern and pattern != args.pattern:
            continue

        # Wire cost per foot
        wire_ft = WIRE_COST_PER_FT.get(pattern)
        if wire_ft is None:
            unknown.append((sku, option, actual_cost, f"no wire cost for {pattern}"))
            continue

        # Yarn cost per foot
        yarn_type = get_yarn_type(decoded)
        yarn_per_100 = get_yarn_per_100ft(decoded)
        if yarn_type and yarn_per_100:
            yarn_unit_cost = yarn_costs.get(yarn_type)
            if yarn_unit_cost is None:
                unknown.append((sku, option, actual_cost, f"unknown yarn type {yarn_type}"))
                continue
            yarn_ft = yarn_unit_cost * yarn_per_100 / 100
        elif yarn_type is None and decoded["family"] == "W121":
            yarn_ft = 0
        else:
            unknown.append((sku, option, actual_cost, "cannot determine yarn cost"))
            continue

        # Quantity from option
        qty = parse_option_qty(option)
        if qty is None:
            unknown.append((sku, option, actual_cost, f"cannot parse qty from '{option}'"))
            continue

        # Spool cost
        spool = get_spool_cost(decoded, qty)
        if spool is None:
            unknown.append((sku, option, actual_cost, f"no spool cost for {pattern} qty={qty}"))
            continue

        expected = calc_cost(wire_ft, yarn_ft, qty, spool)
        diff = round(actual_cost - expected, 2)

        entry = (sku, option, actual_cost, expected, diff)
        if abs(diff) <= 0.01:
            matches.append(entry)
        else:
            mismatches.append(entry)

    # Print results
    print("Wire SKU Cost Audit")
    print("=" * 90)
    print()

    if mismatches or args.all:
        label = "All audited SKUs" if args.all else f"Cost mismatches ({len(mismatches)})"
        print(f"{label}:")
        show = (matches + mismatches) if args.all else mismatches
        for sku, option, actual, expected, diff in sorted(show):
            flag = "  " if abs(diff) <= 0.01 else ">>"
            print(
                f" {flag} {sku:25} {option:30}  actual ${actual:>8.2f}"
                f"  expected ${expected:>8.2f}  diff ${diff:>+7.2f}"
            )
        print()

    if unknown:
        print(f"Could not audit ({len(unknown)}):")
        for sku, option, actual, reason in unknown:
            print(f"    {sku:25} {option:30}  ${actual:>8.2f}  ({reason})")
        print()

    # Summary
    total = len(matches) + len(mismatches) + len(unknown)
    print("=" * 90)
    print(f"Total W-prefix SKUs:  {total}")
    print(f"  Matches:            {len(matches)}")
    print(f"  Mismatches:         {len(mismatches)}")
    print(f"  Could not audit:    {len(unknown)}")
    print("=" * 90)

    return 0 if not mismatches else 1


if __name__ == "__main__":
    sys.exit(main())
