"""Shared YAML loading and SKU construction for product lines.

Used by both the greenlight app and CLI utilities.
"""

import logging
import yaml
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)

PRODUCT_LINES_DIR = Path(__file__).parent.parent / "util" / "product_lines"

PREFIX_MAP = {
    "SC": "Studio Classic",
    "SV": "Studio Vocal",
    "TC": "Tour Classic",
    "TV": "Tour Vocal",
}

LOW_STOCK_THRESHOLD = 2


def _load_economics():
    """Load back_office/economics.yaml → {prefix: {length: {price, cost, cost_ra, weight}}}.

    Consolidates the former pricing.yaml + weights.yaml. Returns {} if absent.
    """
    path = PRODUCT_LINES_DIR / "back_office" / "economics.yaml"
    if not path.exists():
        return {}
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("series", {}) or {}


def _validate_economics(economics, cable_lines_data):
    """Cross-check economics.yaml against the runtime series definitions.

    Raises on structural drift (a series' economics lengths not matching its
    cable_lines lengths). Logs a warning — but does not raise — for individual
    missing price/cost/weight values, so a gap like the old SC-15 missing
    weight surfaces loudly instead of silently syncing nothing.
    """
    errors, warnings = [], []
    for data in cable_lines_data.get("series", []):
        prefix = data.get("sku_prefix")
        if not prefix:
            continue
        want_lengths = set(data.get("lengths", []))
        has_ra = any((c.get("code") or "") == "-R" for c in data.get("connectors", []))

        econ = economics.get(prefix)
        if econ is None:
            errors.append(f"{prefix}: no economics entry")
            continue

        have_lengths = set(econ.keys())
        if want_lengths - have_lengths:
            errors.append(f"{prefix}: economics missing length(s) {sorted(want_lengths - have_lengths)}")
        if have_lengths - want_lengths:
            errors.append(f"{prefix}: economics has length(s) not in cable_lines {sorted(have_lengths - want_lengths)}")

        for length in sorted(want_lengths & have_lengths):
            entry = econ.get(length) or {}
            for field in ("price", "cost", "weight"):
                if entry.get(field) is None:
                    warnings.append(f"{prefix}-{length}: missing {field}")
            if has_ra and entry.get("cost_ra") is None:
                warnings.append(f"{prefix}-{length}: missing cost_ra (series has a right-angle connector)")

    if warnings:
        logger.warning(
            "economics.yaml has %d incomplete value(s):\n  %s",
            len(warnings), "\n  ".join(warnings),
        )
    if errors:
        raise ValueError("economics.yaml structural errors:\n  " + "\n  ".join(errors))


def load_yaml_skus():
    """Load all defined SKUs from YAML product line files.

    Layout:
      cable_lines.yaml           — runtime: sku_prefix, product_line, lengths,
                                   connectors, braid_material
      patterns.yaml              — runtime: pattern catalog
      back_office/economics.yaml — back-office: price + cost + cost_ra + weight
                                   per (series, length) (merged pricing+weights)

    Returns dict: sku_prefix -> {name, lengths, connectors, patterns, pricing, cost, weight}.
    The pricing/cost/weight sub-dicts keep the pre-consolidation shape (cost
    carries '{length}R' keys for right-angle) so downstream callers are
    unchanged — only the source file changed.
    """
    patterns_path = PRODUCT_LINES_DIR / "patterns.yaml"
    with open(patterns_path) as f:
        patterns_data = yaml.safe_load(f)

    patterns_by_fabric = defaultdict(list)
    for p in patterns_data["patterns"]:
        patterns_by_fabric[p["fabric_type"].lower()].append(p)

    cable_lines_path = PRODUCT_LINES_DIR / "cable_lines.yaml"
    with open(cable_lines_path) as f:
        cable_lines_data = yaml.safe_load(f) or {}

    economics = _load_economics()
    _validate_economics(economics, cable_lines_data)

    lines = {}
    for data in cable_lines_data.get("series", []):
        prefix = data.get("sku_prefix")
        if not prefix:
            continue
        fabric = data.get("braid_material", "").lower()
        line_patterns = patterns_by_fabric.get(fabric, [])

        # Reshape economics into the legacy pricing/cost/weight dicts. Skip
        # null values so missing keys stay missing (identical to the old
        # two-file behavior — e.g. SC-15 weight simply won't be present).
        econ = economics.get(prefix, {}) or {}
        pricing, cost, weight = {}, {}, {}
        for length, entry in econ.items():
            entry = entry or {}
            if entry.get("price") is not None:
                pricing[length] = entry["price"]
            if entry.get("cost") is not None:
                cost[length] = entry["cost"]
            if entry.get("cost_ra") is not None:
                cost[f"{length}R"] = entry["cost_ra"]
            if entry.get("weight") is not None:
                weight[length] = entry["weight"]

        lines[prefix] = {
            "name": data["product_line"],
            "lengths": data["lengths"],
            "connectors": data.get("connectors", [{"code": "", "display": ""}]),
            "patterns": line_patterns,
            "pricing": pricing,
            "cost": cost,
            "weight": weight,
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
