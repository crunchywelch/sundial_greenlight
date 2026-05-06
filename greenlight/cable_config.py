"""Cable config resolver — single source of truth for cable attributes.

Loads the YAML config under util/product_lines/ at import time and exposes
helpers to resolve series, patterns, and SKU structure. Mirrors the JS
resolver in shopify_app/app/cable-config.server.js — both are kept honest
by tests/sku_fixtures.json.

SKU model (Phase 4):

  - sku_group: 'SC-SL', 'SC-MISC-42', 'SC-LTD-PHISH26'.
    What the sku_group table stores and what audio_cables.sku_group references.
    parse_group_sku() takes one of these.

  - variant SKU: 'SC-12SL', 'SC-12SL-R', 'SC-MISC-42', 'SC-LTD-PHISH26'.
    The user-facing string Shopify sees in product variants and order line
    items. For catalog cables it embeds length and connector; for MISC/LTD
    it equals the group SKU. parse_variant_sku() takes one of these.
    format_variant_sku() builds one from (sku_group, length, connector_code).

This module is read-only on the YAML and does NOT touch the database.

See docs/CABLE_VARIANTS_REFACTOR.md § Phase 4 for design rationale.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCT_LINES_DIR = _REPO_ROOT / "util" / "product_lines"

# Group SKU regexes
_RE_GROUP_MISC = re.compile(r'^([A-Z]{2,3})-MISC-(\d+)$')
_RE_GROUP_LTD = re.compile(r'^([A-Z]{2,3})-LTD-([A-Z0-9]{4,12})$')
_RE_GROUP_CATALOG = re.compile(r'^([A-Z]{2,3})-([A-Z]{2,3})$')

# Variant SKU regex (catalog only — MISC/LTD variants equal their group SKU)
_RE_VARIANT_CATALOG = re.compile(r'^([A-Z]{2,3})-(\d+)([A-Z]{2,3})(-R)?$')


def _load_patterns():
    path = _PRODUCT_LINES_DIR / "patterns.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    return {p['code']: p for p in data.get('patterns', [])}


def _load_series():
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


_PATTERNS = _load_patterns()
_SERIES = _load_series()


def series_for_prefix(prefix: str) -> Optional[str]:
    """Return the full series name for a SKU prefix, or None if unknown."""
    s = _SERIES.get(prefix)
    return s.get('product_line') if s else None


def series_data_for_prefix(prefix: str) -> Optional[dict]:
    """Return the full series YAML dict for a prefix, or None if unknown."""
    return _SERIES.get(prefix)


def pattern_for_code(code: str) -> Optional[dict]:
    """Return the pattern dict {code, name, fabric_type, description}, or None."""
    return _PATTERNS.get(code)


def prefix_for_series(series_name: str) -> Optional[str]:
    """Reverse lookup: full series name → SKU prefix. None if unknown."""
    if not series_name:
        return None
    for prefix, data in _SERIES.items():
        if data.get('product_line') == series_name:
            return prefix
    return None


def connector_display_for(series_prefix: str, connector_code: str) -> Optional[str]:
    """Look up the connector display string for a series + code, or None.

    Useful for callers that have a (sku_group, connector_code) pair and want
    the display string — including MISC/LTD cables where the connector code
    isn't encoded in the variant SKU.
    """
    s = _SERIES.get(series_prefix)
    if not s:
        return None
    for conn in s.get('connectors', []):
        if (conn.get('code') or '') == connector_code:
            return conn.get('display')
    return None


# Internal alias retained for parse_variant_sku.
_connector_display = connector_display_for


def parse_group_sku(sku: str) -> dict:
    """Parse a sku_group identifier into structural components + YAML lookups.

    Returns dict with at least 'kind'. For parseable group SKUs:
      - 'catalog': prefix, series, pattern_code, pattern_name
      - 'misc':    prefix, series, misc_seq
      - 'ltd':     prefix, series, slug

    Unknown prefix or pattern code yields a parsed result with the unknown
    field's resolved name None. Truly malformed inputs return {'kind': None}.
    """
    if not sku or not isinstance(sku, str):
        return {'kind': None}

    m = _RE_GROUP_MISC.match(sku)
    if m:
        prefix = m.group(1)
        return {
            'kind': 'misc',
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'misc_seq': int(m.group(2)),
        }

    m = _RE_GROUP_LTD.match(sku)
    if m:
        prefix, slug = m.group(1), m.group(2)
        return {
            'kind': 'ltd',
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'slug': slug,
        }

    m = _RE_GROUP_CATALOG.match(sku)
    if m:
        prefix, pattern_code = m.group(1), m.group(2)
        pattern = pattern_for_code(pattern_code)
        return {
            'kind': 'catalog',
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'pattern_code': pattern_code,
            'pattern_name': pattern.get('name') if pattern else None,
        }

    return {'kind': None}


def parse_variant_sku(sku: str) -> dict:
    """Parse a variant SKU string into structural components.

    Catalog variants ('SC-12SL', 'SC-12SL-R') decompose into group_sku, length,
    pattern_code, connector_code. MISC and LTD variant strings equal their
    group SKU; this function recognises them and returns kind+group_sku, with
    length/connector fields absent.

    Returns {'kind': None} on malformed input.
    """
    if not sku or not isinstance(sku, str):
        return {'kind': None}

    m = _RE_GROUP_MISC.match(sku)
    if m:
        prefix = m.group(1)
        return {
            'kind': 'misc',
            'group_sku': sku,
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'misc_seq': int(m.group(2)),
        }

    m = _RE_GROUP_LTD.match(sku)
    if m:
        prefix, slug = m.group(1), m.group(2)
        return {
            'kind': 'ltd',
            'group_sku': sku,
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'slug': slug,
        }

    m = _RE_VARIANT_CATALOG.match(sku)
    if m:
        prefix = m.group(1)
        length = int(m.group(2))
        pattern_code = m.group(3)
        connector_code = m.group(4) or ''
        pattern = pattern_for_code(pattern_code)
        return {
            'kind': 'catalog',
            'group_sku': f"{prefix}-{pattern_code}",
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'length': length,
            'pattern_code': pattern_code,
            'pattern_name': pattern.get('name') if pattern else None,
            'connector_code': connector_code,
            'connector_display': _connector_display(prefix, connector_code),
        }

    return {'kind': None}


def format_variant_sku(group_sku=None, length=None, connector_code=None) -> Optional[str]:
    """Build a user-facing variant SKU string from a sku_group + per-cable attrs.

    For catalog groups: '{prefix}-{length}{pattern_code}{connector_code}'.
    For MISC/LTD groups: returns the group SKU verbatim (length/connector_code
    are properties of the cable but don't appear in the SKU string).

    Returns None if the group_sku doesn't parse.
    """
    parsed = parse_group_sku(group_sku)
    kind = parsed.get('kind')
    if kind is None:
        return None
    if kind in ('misc', 'ltd'):
        return group_sku
    # catalog: need length + pattern_code
    if length is None:
        return None
    cc = connector_code or ''
    # length comes through as int (parsed) or float (Decimal-coerced); cast cleanly.
    if isinstance(length, float) and length.is_integer():
        length_str = str(int(length))
    else:
        length_str = str(length)
    return f"{parsed['prefix']}-{length_str}{parsed['pattern_code']}{cc}"


def all_prefixes() -> list:
    """All known series prefixes (sorted)."""
    return sorted(_SERIES.keys())


def all_patterns() -> list:
    """All known patterns (list of dicts)."""
    return list(_PATTERNS.values())
