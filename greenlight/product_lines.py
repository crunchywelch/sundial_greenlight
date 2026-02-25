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


def interpolate_cost(lengths_map, target_length):
    """Interpolate a value from a length-keyed map for a non-standard length.

    Finds the two nearest standard lengths and linearly interpolates.
    Extrapolates if target is outside the range.
    """
    if not lengths_map:
        return None

    # Sort by numeric length key, skipping R-suffix keys
    points = sorted((float(k), float(v)) for k, v in lengths_map.items()
                    if not isinstance(k, str) or not k.endswith('R'))

    if not points:
        return None

    target = float(target_length)

    # Exact match
    for l, v in points:
        if abs(l - target) < 0.01:
            return v

    # Find bracketing points
    below = [(l, v) for l, v in points if l < target]
    above = [(l, v) for l, v in points if l > target]

    if below and above:
        l1, v1 = below[-1]
        l2, v2 = above[0]
    elif below:
        # Extrapolate above using last two points
        if len(points) >= 2:
            l1, v1 = points[-2]
            l2, v2 = points[-1]
        else:
            return points[-1][1]
    else:
        # Extrapolate below using first two points
        if len(points) >= 2:
            l1, v1 = points[0]
            l2, v2 = points[1]
        else:
            return points[0][1]

    rate = (v2 - v1) / (l2 - l1)
    return round(v1 + rate * (target - l1), 2)


def get_cost_for_special_baby(series, length):
    """Get interpolated cost for a special baby cable given series name and length.

    Returns cost as a float, or None if data is unavailable.
    """
    if not series or not length:
        return None

    lines = load_yaml_skus()

    # Map series name to prefix (e.g., "Studio Classic" -> "SC")
    # PREFIX_MAP is prefix->name, we need name->prefix
    name_to_prefix = {v.lower(): k for k, v in PREFIX_MAP.items()}
    prefix = name_to_prefix.get(series.lower())
    if not prefix:
        return None

    line = lines.get(prefix)
    if not line:
        return None

    cost_map = line.get("cost", {})
    if not cost_map:
        return None

    return interpolate_cost(cost_map, length)
