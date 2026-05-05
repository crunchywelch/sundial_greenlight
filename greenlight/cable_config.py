"""Cable config resolver — single source of truth for cable attributes.

Loads the YAML config under util/product_lines/ at import time and exposes
helpers to resolve series, patterns, and SKU structure. Mirrors the JS
resolver in shopify_app/app/cable-config.server.js — both are kept honest
by tests/sku_fixtures.json.

This module is read-only. It does NOT touch the database. Callers that need
DB-backed fields (length for MISC/LTD, descriptions for variants) read those
from cable_skus separately and combine with the resolver's output.

See docs/CABLE_VARIANTS_REFACTOR.md § Phase 3 for design rationale.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

# Path resolution: this file lives at greenlight/cable_config.py;
# YAML is at <repo_root>/util/product_lines/.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCT_LINES_DIR = _REPO_ROOT / "util" / "product_lines"

# SKU pattern regexes
_RE_MISC = re.compile(r'^([A-Z]{2,3})-MISC-(\d+)$')
_RE_LTD = re.compile(r'^([A-Z]{2,3})-LTD-([A-Z0-9]{4,12})$')
_RE_CATALOG = re.compile(r'^([A-Z]{2,3})-(\d+)([A-Z]{2,3})(-R)?$')


def _load_patterns():
    path = _PRODUCT_LINES_DIR / "patterns.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return {p['code']: p for p in data.get('patterns', [])}


def _load_series():
    """Load each per-series YAML file. Returns dict keyed by sku_prefix."""
    series_files = ['studio_classic.yaml', 'studio_vocal.yaml',
                    'tour_classic.yaml', 'tour_vocal.yaml']
    by_prefix = {}
    for fname in series_files:
        path = _PRODUCT_LINES_DIR / fname
        if not path.exists():
            logger.warning("Series YAML missing: %s", path)
            continue
        with open(path) as f:
            data = yaml.safe_load(f)
        prefix = data.get('sku_prefix')
        if not prefix:
            logger.warning("Series YAML %s has no sku_prefix; skipping", fname)
            continue
        by_prefix[prefix] = data
    return by_prefix


# Cache YAML at import time. Both apps load once at startup.
_PATTERNS = _load_patterns()
_SERIES = _load_series()


def series_for_prefix(prefix: str) -> Optional[str]:
    """Return the full series name for a SKU prefix, or None if unknown."""
    s = _SERIES.get(prefix)
    return s.get('product_line') if s else None


def series_data_for_prefix(prefix: str) -> Optional[dict]:
    """Return the full series YAML data for a prefix (product_line, core_cable,
    braid_material, lengths[], connectors[], cost[]), or None if unknown.

    Use series_for_prefix when only the name is needed; this is for callers
    that need the full series spec (e.g. attribute defaults for variants).
    """
    return _SERIES.get(prefix)


def pattern_for_code(code: str) -> Optional[dict]:
    """Return the pattern dict {code, name, fabric_type, description}, or None."""
    return _PATTERNS.get(code)


def prefix_for_series(series_name: str) -> Optional[str]:
    """Reverse lookup: full series name → SKU prefix. Returns None if unknown.

    Useful when an existing API takes a series name (e.g. 'Studio Classic')
    and we need to filter cable_skus by SKU prefix instead.
    """
    for prefix, data in _SERIES.items():
        if data.get('product_line') == series_name:
            return prefix
    return None


def _connector_display(series_prefix: str, connector_code: str) -> Optional[str]:
    """Look up the connector display string for a series + code, or None."""
    s = _SERIES.get(series_prefix)
    if not s:
        return None
    for conn in s.get('connectors', []):
        if conn.get('code', '') == connector_code:
            return conn.get('display')
    return None


def parse_sku(sku: str) -> dict:
    """Parse a SKU into its structural components + YAML-resolved names.

    Returns a dict with at least 'kind'. For parseable SKUs:
      - 'catalog': series_prefix, series, length, pattern_code, pattern_name,
                   connector_code, connector_display
      - 'misc': series_prefix, series  (length lives on cable_skus.length)
      - 'ltd': series_prefix, series, slug  (length lives on cable_skus.length)

    Unknown prefix or pattern code yields kind='catalog' with the unknown
    field's resolved name as None — structural parse stays useful for
    diagnostics. Truly malformed inputs (no recognized shape) return
    {'kind': None}.
    """
    if not sku or not isinstance(sku, str):
        return {'kind': None}

    # MISC variant: {prefix}-MISC-{seq}
    m = _RE_MISC.match(sku)
    if m:
        prefix = m.group(1)
        return {
            'kind': 'misc',
            'series_prefix': prefix,
            'series': series_for_prefix(prefix),
        }

    # LTD edition: {prefix}-LTD-{slug}
    m = _RE_LTD.match(sku)
    if m:
        prefix, slug = m.group(1), m.group(2)
        return {
            'kind': 'ltd',
            'series_prefix': prefix,
            'series': series_for_prefix(prefix),
            'slug': slug,
        }

    # Catalog SKU: {prefix}-{length}{pattern}{?-R}
    m = _RE_CATALOG.match(sku)
    if m:
        prefix = m.group(1)
        length = int(m.group(2))
        pattern_code = m.group(3)
        connector_code = m.group(4) or ''  # '-R' or ''
        pattern = pattern_for_code(pattern_code)
        return {
            'kind': 'catalog',
            'series_prefix': prefix,
            'series': series_for_prefix(prefix),
            'length': length,
            'pattern_code': pattern_code,
            'pattern_name': pattern.get('name') if pattern else None,
            'connector_code': connector_code,
            'connector_display': _connector_display(prefix, connector_code),
        }

    return {'kind': None}


def all_prefixes() -> list:
    """Return all known series prefixes (sorted)."""
    return sorted(_SERIES.keys())


def all_patterns() -> list:
    """Return all known patterns (list of dicts)."""
    return list(_PATTERNS.values())
