"""Cable config resolver — single source of truth for cable attributes.

Loads the YAML config under util/product_lines/ at import time and exposes
helpers to resolve series, patterns, and SKU structure. Mirrors the JS
resolver in shopify_app/app/cable-config.server.js — both are kept honest
by tests/sku_fixtures.json.

SKU model (Phase 5):

  - sku_group identifier: what `sku_group.sku` stores and what
    `audio_cables.sku_group` references. Series prefix lives on
    audio_cables.prefix, not in the group SKU (except for MISC groups,
    which stay series-scoped).
      catalog: 'GL', 'SL', 'BU', ... (just the pattern code)
      ltd:     'LTD-PHISH26' (series-agnostic — LTD editions span series)
      misc:    'SC-MISC-42' (still series-scoped)

  - variant SKU: the user-facing string Shopify sees in product variants
    and order line items. Always series-specific and fully qualified for
    catalog and LTD (length and connector embedded):
      catalog: 'SC-12GL', 'SC-12GL-R'
      ltd:     'SC-12-LTD-PHISH26', 'SC-12-LTD-PHISH26-R'
      misc:    'SC-MISC-42' (== group SKU)

This module is read-only on the YAML and does NOT touch the database.

See docs/CABLE_VARIANTS_REFACTOR.md § Phase 5 for design rationale.
"""

import logging
import re
from pathlib import Path
from typing import Optional

import yaml
from jsonschema import Draft7Validator

from greenlight.cable_config_schemas import CABLE_LINES_SCHEMA, PATTERNS_SCHEMA

logger = logging.getLogger(__name__)


def _validate(data, schema, file_label):
    """Validate parsed YAML against a schema; collect every error and raise.

    Mirrors the JS allErrors=true behavior — if patterns.yaml has 5 typos,
    the operator sees all 5 at once instead of one fix-and-rerun cycle per
    typo. Throws ValueError with a multi-line message.
    """
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    lines = []
    for e in errors:
        path = "/" + "/".join(str(p) for p in e.absolute_path) if e.absolute_path else "(root)"
        lines.append(f"  - {path} {e.message}")
    raise ValueError(f"Invalid {file_label}:\n" + "\n".join(lines))

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PRODUCT_LINES_DIR = _REPO_ROOT / "util" / "product_lines"

# Group SKU regexes (Phase 5)
_RE_GROUP_MISC = re.compile(r'^([A-Z]{2,3})-MISC-(\d+)$')
_RE_GROUP_LTD = re.compile(r'^LTD-([A-Z0-9]{4,24})$')
_RE_GROUP_CATALOG = re.compile(r'^([A-Z]{2,3})$')

# Variant SKU regexes (variants are series-specific and fully qualified —
# they carry length and connector code per-cable for both catalog AND LTD).
#   catalog: '{prefix}-{length}{pattern}{?-R}' — 'SC-12GL', 'SC-12GL-R'
#   ltd:     '{prefix}-{length}-LTD-{slug}{?-R}' — 'SC-12-LTD-PHISH26-R'
#   misc:    '{prefix}-MISC-{seq}' — equals the group SKU, untouched
_RE_VARIANT_CATALOG = re.compile(r'^([A-Z]{2,3})-(\d+)([A-Z]{2,3})(-R)?$')
_RE_VARIANT_LTD = re.compile(r'^([A-Z]{2,3})-(\d+)-LTD-([A-Z0-9]{4,24})(-R)?$')


def _load_patterns():
    path = _PRODUCT_LINES_DIR / "patterns.yaml"
    with open(path) as f:
        data = yaml.safe_load(f)
    _validate(data, PATTERNS_SCHEMA, "patterns.yaml")
    return {p['code']: p for p in data['patterns']}


def _load_series():
    """Load every series spec from cable_lines.yaml, keyed by sku_prefix.

    Single-file layout (post-2026-05-06 reorg): cable_lines.yaml has a top-
    level `series:` list of dicts, each with sku_prefix / product_line /
    core_cable / braid_material / lengths / connectors. Cost / pricing /
    weight tables now live under back_office/ and are NOT loaded here —
    they're back-office data, read only by util/audio scripts.
    """
    path = _PRODUCT_LINES_DIR / "cable_lines.yaml"
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    _validate(data, CABLE_LINES_SCHEMA, "cable_lines.yaml")
    return {s['sku_prefix']: s for s in data['series']}


_PATTERNS = _load_patterns()
_SERIES = _load_series()


def series_for_prefix(prefix: str) -> Optional[str]:
    """Return the full series name for a SKU prefix, or None if unknown."""
    s = _SERIES.get(prefix)
    return s.get('product_line') if s else None


def series_data_for_prefix(prefix: str) -> Optional[dict]:
    """Return the full series YAML dict for a prefix, or None."""
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
    """Look up the connector display string for (series_prefix, connector_code)."""
    s = _SERIES.get(series_prefix)
    if not s:
        return None
    for conn in s.get('connectors', []):
        if (conn.get('code') or '') == connector_code:
            return conn.get('display')
    return None


def parse_group_sku(sku: str) -> dict:
    """Parse a sku_group identifier.

    Group SKUs are series-agnostic for catalog and LTD (Phase 5). Per-kind
    return shape:
      - 'catalog': pattern_code, pattern_name
      - 'misc':    prefix, series, misc_seq
      - 'ltd':     slug

    Unknown pattern code yields kind='catalog' with pattern_name=None. Truly
    malformed inputs return {'kind': None}.
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
        return {'kind': 'ltd', 'slug': m.group(1)}

    m = _RE_GROUP_CATALOG.match(sku)
    if m:
        pattern_code = m.group(1)
        pattern = pattern_for_code(pattern_code)
        return {
            'kind': 'catalog',
            'pattern_code': pattern_code,
            'pattern_name': pattern.get('name') if pattern else None,
        }

    return {'kind': None}


def parse_variant_sku(sku: str) -> dict:
    """Parse a user-facing variant SKU string.

    Variant SKUs are always series-specific. Returns group_sku derived from
    the variant. Per-kind result shape:
      - 'catalog': group_sku ('GL'), prefix, series, length, pattern_code,
                   pattern_name, connector_code, connector_display
      - 'misc':    group_sku (== sku), prefix, series, misc_seq
      - 'ltd':     group_sku ('LTD-{slug}'), prefix, series, slug

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

    m = _RE_VARIANT_LTD.match(sku)
    if m:
        prefix = m.group(1)
        length = int(m.group(2))
        slug = m.group(3)
        connector_code = m.group(4) or ''
        return {
            'kind': 'ltd',
            'group_sku': f"LTD-{slug}",
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'length': length,
            'slug': slug,
            'connector_code': connector_code,
            'connector_display': connector_display_for(prefix, connector_code),
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
            'group_sku': pattern_code,
            'prefix': prefix,
            'series': series_for_prefix(prefix),
            'length': length,
            'pattern_code': pattern_code,
            'pattern_name': pattern.get('name') if pattern else None,
            'connector_code': connector_code,
            'connector_display': connector_display_for(prefix, connector_code),
        }

    return {'kind': None}


def format_variant_sku(group_sku=None, prefix=None, length=None, connector_code=None) -> Optional[str]:
    """Build a user-facing variant SKU from a group_sku + per-cable attrs.

    Catalog: '{prefix}-{length}{pattern_code}{connector_code}' — needs prefix
      from audio_cables since the catalog group SKU doesn't carry it.
    LTD:     '{prefix}-{length}-LTD-{slug}{connector_code}' — fully qualified
      per-cable so a right-angle 12ft Studio Classic in the PHISH26 edition
      reads as 'SC-12-LTD-PHISH26-R'. Group SKU stays edition-only.
    MISC:    returns group_sku verbatim (which still includes the prefix).

    Returns None if inputs are invalid.
    """
    parsed = parse_group_sku(group_sku)
    kind = parsed.get('kind')
    if kind is None:
        return None

    if kind == 'misc':
        return group_sku

    def _length_str(val):
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return str(val)

    if kind == 'ltd':
        if not prefix or length is None:
            return None
        cc = connector_code or ''
        return f"{prefix}-{_length_str(length)}-LTD-{parsed['slug']}{cc}"

    # catalog
    if not prefix or length is None:
        return None
    cc = connector_code or ''
    return f"{prefix}-{_length_str(length)}{parsed['pattern_code']}{cc}"


def all_prefixes() -> list:
    """All known series prefixes (sorted)."""
    return sorted(_SERIES.keys())


def all_patterns() -> list:
    """All known patterns (list of dicts)."""
    return list(_PATTERNS.values())
