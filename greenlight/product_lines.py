"""Shared YAML loading and SKU construction for product lines.

Used by both the greenlight app and CLI utilities.
"""

import yaml
from pathlib import Path
from collections import defaultdict


PRODUCT_LINES_DIR = Path(__file__).parent.parent / "util" / "product_lines"

PREFIX_MAP = {
    "SC": "Studio Classic",
    "SV": "Studio Vocal",
    "TC": "Tour Classic",
    "TV": "Tour Vocal",
}

LOW_STOCK_THRESHOLD = 2


def load_yaml_skus():
    """Load all defined SKUs from YAML product line files.

    Returns dict: sku_prefix -> {name, lengths, connectors, patterns, pricing, cost}
    """
    patterns_path = PRODUCT_LINES_DIR / "patterns.yaml"
    with open(patterns_path) as f:
        patterns_data = yaml.safe_load(f)

    patterns_by_fabric = defaultdict(list)
    for p in patterns_data["patterns"]:
        patterns_by_fabric[p["fabric_type"].lower()].append(p)

    lines = {}
    for yaml_file in sorted(PRODUCT_LINES_DIR.glob("*.yaml")):
        if yaml_file.name in ("patterns.yaml", "materials.yaml"):
            continue
        with open(yaml_file) as f:
            data = yaml.safe_load(f)

        prefix = data["sku_prefix"]
        fabric = data.get("braid_material", "").lower()
        line_patterns = patterns_by_fabric.get(fabric, [])

        lines[prefix] = {
            "name": data["product_line"],
            "lengths": data["lengths"],
            "connectors": data.get("connectors", [{"code": "", "display": ""}]),
            "patterns": line_patterns,
            "pricing": data.get("pricing", {}),
            "cost": data.get("cost", {}),
        }
    return lines


def build_sku(prefix, length, pattern_code, connector_code):
    """Build a SKU string from components."""
    base = f"{prefix}-{length}{pattern_code}"
    if connector_code:
        base += connector_code
    return base


def get_cost(line, length, connector_code):
    """Look up unit cost from YAML cost map."""
    cost_map = line.get("cost", {})
    if connector_code == "-R":
        key = f"{length}R"
        if key in cost_map:
            return cost_map[key]
    return cost_map.get(length)
