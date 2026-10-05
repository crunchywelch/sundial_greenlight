"""Cable config resolver — single source of truth for cable attributes.

Loads the YAML config under catalog/ at import time and exposes
helpers to resolve series, patterns, and SKU structure. Mirrors the JS
resolver in shopify_app/app/cable-config.server.js — both are kept honest
by tests/fixtures/sku_fixtures.json.

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
_PRODUCT_LINES_DIR = _REPO_ROOT / "catalog"

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
    they're back-office data, read only by tools/audio scripts.
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


# Connector finish is a per-cable attribute used ONLY for custom (MISC) and
# limited-edition (LTD) builds. The standard catalog (the YAML above) always
# pairs cotton/Tour with nickel and rayon/Studio with black, so catalog cables
# leave this unset and the series-based heuristic still applies. `conductive_shell`
# drives whether the XLR shell-bond test (XSHELL) runs: nickel shells bond to
# pin 1, but black/gold Neutrik shells are coated and don't, so testing them
# would falsely fail.
CONNECTOR_FINISHES = {
    'nickel':     {'display': 'Nickel',     'conductive_shell': True},
    'black_gold': {'display': 'Black/Gold', 'conductive_shell': False},
}


def finish_display(finish_code: str) -> Optional[str]:
    """Display string for a connector finish code; None if unset."""
    if not finish_code:
        return None
    info = CONNECTOR_FINISHES.get(finish_code)
    return info['display'] if info else finish_code


def finish_tests_shell(finish_code: str) -> bool:
    """Whether a connector finish has a conductive shell worth bond-testing.

    Unknown/blank finishes default to True; callers should gate on whether a
    finish is actually set before relying on this (an unset finish means
    'use the series heuristic', not 'force the shell test').
    """
    info = CONNECTOR_FINISHES.get(finish_code)
    return info['conductive_shell'] if info else True


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


# What KIND of cable this is, for retail, plus how its connectors are named.
# A customer browsing a shelf is picking by length and by what it plugs into,
# so `type` is the big line ("20' Instrument") and `label` is the connector
# designation printed under it.
#
# `connector_display_for` returns the engineering shorthand ('RA-TS') that the
# rest of the system runs on. `label` is the product-facing form of the same
# thing: both ends of a right-angle cable really are TS, one of them angled,
# so it reads "TS-TS Right Angle" rather than inventing a second pair name.
# Keys are the ASCII-folded display strings from cable_lines.yaml.
#
# Nothing here states what can't be otherwise: a mic cable is always XLR male
# to female, so no entry says so.
#
# Three rules for a new entry, each with a test behind it:
#
#   - `type` fits the spec row: that row is font "5" and holds 18 characters,
#     and "25' " spends 4, so a type word has 14.
#   - `label` fits its row: font "2", 48 characters.
#   - No `"` in either. TSPL quotes TEXT content with double quotes and has no
#     escape for one, so the templates substitute `'` — which would turn 1/4"
#     into 1/4', i.e. feet. Feet use the prime (20'); inch marks never appear.
RETAIL_CABLE_TYPES = {
    # In the catalog today:
    'TS-TS':   {'type': 'Instrument', 'label': 'TS-TS'},
    'RA-TS':   {'type': 'Instrument', 'label': 'TS-TS Right Angle'},
    'XLR-XLR': {'type': 'Microphone', 'label': 'XLR-XLR'},
    # Not built yet; placeholders so a new series doesn't print a blank row.
    # Revisit the wording when one actually ships.
    'TRS-TRS': {'type': 'Instrument', 'label': 'TRS-TRS'},
    'TS-TRS':  {'type': 'Instrument', 'label': 'TS-TRS'},
    'XLR-TRS': {'type': 'Microphone', 'label': 'XLR-TRS'},
}


def _ascii_dashes(text: Optional[str]) -> Optional[str]:
    """Fold en/em dashes to ASCII hyphens; cable_lines.yaml uses en-dashes."""
    if not text:
        return text
    return text.replace('\u2013', '-').replace('\u2014', '-')


def retail_cable_type(connector_display: str) -> dict:
    """What a shopper calls this cable, from its connector display string.

    Returns {'type': 'Instrument', 'label': 'TS-TS Right Angle'}, or
    {'type': None, 'label': None} for an unmapped or missing connector.
    """
    if not connector_display:
        return {'type': None, 'label': None}
    entry = RETAIL_CABLE_TYPES.get(_ascii_dashes(connector_display))
    return dict(entry) if entry else {'type': None, 'label': None}


def _length_display(length) -> str:
    """Feet as a label prints them: '20', and '2.5' rather than '2.5000'."""
    if isinstance(length, float) and length.is_integer():
        return str(int(length))
    return str(length)


def describe_variant(sku: str) -> Optional[dict]:
    """Display strings for one variant SKU, for customer-facing labels.

    Pure catalog lookup — no DB and no Shopify — so retail labels still print
    with Postgres down and the tunnel off (the same constraint `gtin.py`
    carries for box labels).

    Returns None if the SKU doesn't parse. Otherwise, the atoms:

        sku                 'SC-20GL' (as given)
        kind                'catalog' | 'ltd' | 'misc'
        length              '20' — bare feet, no unit (None for MISC)
        cable_type          'Instrument' | 'Microphone' — the shopper's word
        connector_label     'TS-TS' | 'TS-TS Right Angle' — the connector
                            designation on its own
        connector           'RA-TS'  (ASCII-folded engineering shorthand; NOT
                            printed on retail labels)
        retail_family       'Studio' | 'Touring' — coarse family name for the
                            retail box, from cable_lines.yaml
        series              'Studio Classic'
        pattern             'Goldline'  (None for LTD/MISC)
        pattern_description 'Black rayon braid with gold tracer'
        core_cable          'Canare GS-6'
        braid_material      'Rayon'

    plus the four lines a retail shelf label prints verbatim, top to bottom:

        brand_line          'Sundial Audio Studio Series'
        pattern             'Goldline'  (None for LTD/MISC)
        spec_line           "20' Instrument Cable"
        connector_line      'TS-TS - Canare GS-6' — the connector designation
                            plus the core cable. The core rides here rather
                            than leading the description because the
                            description prints large enough that the two
                            together would overrun its two rows (110
                            characters against 96).
        detail              'Canare GS-6 core - black rayon braid with gold
                             tracer'

    `headline` ('Studio Classic - Goldline') is kept for callers that want
    series and pattern in one string; the shelf label no longer uses it.
    """
    parsed = parse_variant_sku(sku)
    kind = parsed.get('kind')
    if kind is None:
        return None

    series_data = series_data_for_prefix(parsed['prefix']) or {}
    series = parsed.get('series')
    # Fall back to the full product_line if a series predates retail_family.
    family = series_data.get('retail_family') or series
    core_cable = series_data.get('core_cable')
    braid = series_data.get('braid_material')

    pattern = pattern_for_code(parsed['pattern_code']) if kind == 'catalog' else None
    pattern_name = pattern.get('name') if pattern else None
    pattern_desc = pattern.get('description') if pattern else None

    length = parsed.get('length')
    connector = _ascii_dashes(parsed.get('connector_display'))
    cable_type = retail_cable_type(connector)

    # Headline: what cable this is. LTD editions name the edition in place of
    # a pattern; MISC one-offs have neither, so the series stands alone.
    if pattern_name:
        headline = f"{series} - {pattern_name}" if series else pattern_name
    elif kind == 'ltd':
        headline = f"{series} - {parsed['slug']}" if series else parsed['slug']
    else:
        headline = series or ''

    # Detail: the braid copy, and nothing else. A catalog pattern's
    # description already names its braid material, so a bare braid_material
    # only stands in for LTD and MISC builds, which have no pattern.
    detail = pattern_desc or (f"{braid} braid" if braid else '')

    # "20' Instrument" uses the prime for feet, which is safe in TSPL -- only
    # the double quote is unescapable, which is why no inch marks appear
    # anywhere on these labels.
    brand_line = f"Sundial Audio {family} Series" if family else "Sundial Audio"
    spec_bits = []
    if length is not None:
        spec_bits.append(f"{_length_display(length)}'")
    if cable_type['type']:
        spec_bits.append(cable_type['type'])
    spec_line = (' '.join(spec_bits) + ' Cable') if spec_bits else ''

    # Connector designation plus the core cable. Canare is the part of the
    # spec a customer recognizes, so it stays on the label -- just not at the
    # head of the description, which now prints too large to carry both.
    conn_bits = [b for b in (cable_type['label'], core_cable) if b]
    connector_line = ' - '.join(conn_bits)

    return {
        'sku': sku,
        'kind': kind,
        'length': _length_display(length) if length is not None else None,
        'cable_type': cable_type['type'],
        'connector_label': cable_type['label'],
        'connector_line': connector_line,
        'connector': connector,
        'retail_family': family,
        'brand_line': brand_line,
        'spec_line': spec_line,
        'series': series,
        'pattern': pattern_name,
        'pattern_description': pattern_desc,
        'core_cable': core_cable,
        'braid_material': braid,
        'headline': headline,
        'detail': detail,
    }


def all_prefixes() -> list:
    """All known series prefixes (sorted)."""
    return sorted(_SERIES.keys())


def all_patterns() -> list:
    """All known patterns (list of dicts)."""
    return list(_PATTERNS.values())


def all_series() -> list:
    """All series dicts from cable_lines.yaml, in file order."""
    return list(_SERIES.values())
