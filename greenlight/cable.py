from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from greenlight.db import pg_pool
from greenlight.enums import fetch_enum_values
from greenlight.hardware.interfaces import hardware_manager
from greenlight.cable_config import (
    series_for_prefix, prefix_for_series, series_data_for_prefix,
    pattern_for_code, all_prefixes, all_patterns,
)


def get_all_skus():
    """Fetch all sku_group SKUs from the database."""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT sku FROM sku_group ORDER BY sku")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        print(f"Error fetching SKUs: {e}")
        return []
    finally:
        pg_pool.putconn(conn)


def filter_skus(partial_sku, all_skus):
    """Filter SKUs that match the partial input"""
    if not partial_sku:
        return all_skus[:20]  # Show first 20 if no input

    partial_upper = partial_sku.upper()
    filtered = [sku for sku in all_skus if sku.upper().startswith(partial_upper)]
    return filtered[:20]  # Limit to 20 results


# The discovery functions below all read from YAML now (no DB queries). The
# previous DB-driven implementations queried distinct series/color_pattern/etc
# from cable_skus columns that go away in Phase 3.5. YAML is the canonical
# source for "what attribute combinations are available" — the DB only tracks
# which specific SKUs have been generated.

def get_distinct_series():
    """All product series, sorted alphabetically. Sourced from YAML."""
    return sorted(s for s in (series_for_prefix(p) for p in all_prefixes()) if s)


def get_distinct_color_patterns(series=None):
    """Pattern names available for the selected series (or all series).

    Filters by the series' fabric_type — only rayon patterns appear for rayon
    series, only cotton patterns appear for cotton series. Sourced from
    patterns.yaml + the per-series YAML's braid_material.
    """
    if series is None:
        return sorted({p['name'] for p in all_patterns()})

    prefix = prefix_for_series(series)
    if prefix is None:
        return []
    series_data = series_data_for_prefix(prefix)
    if not series_data:
        return []
    fabric_type = (series_data.get('braid_material') or '').lower()
    matching = [p['name'] for p in all_patterns()
                if p.get('fabric_type', '').lower() == fabric_type]
    return sorted(matching)


def get_distinct_lengths(series=None, color_pattern=None):
    """Lengths offered for a series (color_pattern is informational here —
    every pattern that fits the series is available in every length).

    Sourced from the per-series YAML's lengths[] list.
    """
    if series is None:
        # Union of every series' lengths
        lengths = set()
        for prefix in all_prefixes():
            data = series_data_for_prefix(prefix)
            if data:
                lengths.update(data.get('lengths', []))
        return sorted(lengths)

    prefix = prefix_for_series(series)
    if prefix is None:
        return []
    data = series_data_for_prefix(prefix)
    if not data:
        return []
    # Format consistently with what audio_sync_skus.format_length_for_sku does.
    # The screens generally treat lengths as strings for SKU construction.
    return [str(l) if l >= 1 else '06' for l in sorted(data.get('lengths', []))]


def get_distinct_connector_types(series=None, color_pattern=None, length=None):
    """Connector display strings offered for a series (e.g. 'TS–TS', 'RA–TS',
    'XLR–XLR'). Sourced from the per-series YAML's connectors[] list."""
    if series is None:
        # Union across all series
        out = set()
        for prefix in all_prefixes():
            data = series_data_for_prefix(prefix)
            if data:
                for c in data.get('connectors', []):
                    if c.get('display'):
                        out.add(c['display'])
        return sorted(out)

    prefix = prefix_for_series(series)
    if prefix is None:
        return []
    data = series_data_for_prefix(prefix)
    if not data:
        return []
    return [c['display'] for c in data.get('connectors', []) if c.get('display')]


def _connector_code_for_display(prefix, display):
    """Reverse lookup: connector display string → SKU connector code (e.g.
    'RA–TS' → '-R'). Returns None if no match."""
    data = series_data_for_prefix(prefix)
    if not data:
        return None
    for conn in data.get('connectors', []):
        if conn.get('display') == display:
            return conn.get('code') or ''
    return None


def _pattern_code_for_name(name, fabric_type=None):
    """Reverse lookup: pattern name → pattern code, optionally filtered by
    fabric_type. Returns None if not found."""
    for p in all_patterns():
        if p.get('name') != name:
            continue
        if fabric_type and p.get('fabric_type', '').lower() != fabric_type.lower():
            continue
        return p.get('code')
    return None


def resolve_catalog_variant(series, color_pattern, length, connector_type):
    """Resolve catalog screen selections to a (sku_group, length, connector_code) tuple.

    Catalog scan flow: operator picks series → pattern → length → connector,
    we map those back to YAML codes, ensure the sku_group row exists (auto-
    seeded on first encounter post-Phase-4), and return the tuple the
    register_scanned_cable call needs.

    Returns dict with sku_group, length (numeric), connector_code, or None
    if any lookup fails.
    """
    from greenlight.db import ensure_catalog_sku_group

    prefix = prefix_for_series(series)
    if prefix is None:
        return None

    series_data = series_data_for_prefix(prefix)
    if not series_data:
        return None

    pattern_code = _pattern_code_for_name(
        color_pattern, fabric_type=series_data.get('braid_material'))
    if pattern_code is None:
        return None

    connector_code = _connector_code_for_display(prefix, connector_type)
    if connector_code is None:
        return None

    sku_group = ensure_catalog_sku_group(prefix, pattern_code)
    if sku_group is None:
        return None

    # Length comes in as a string like '12' or '06' from the screens.
    try:
        length_num = float(length)
    except (TypeError, ValueError):
        return None

    return {
        'sku_group': sku_group,
        'length': length_num,
        'connector_code': connector_code,
    }


class CableType:
    """Represents a sku_group — the kind-of-cable identity.

    Phase 4: length and connector_code are per-cable attributes (lives on
    audio_cables), NOT on CableType. Pickers and creation flows resolve to
    a sku_group; the screen layer carries length+connector_code separately
    in the navigation context until register_scanned_cable is called.
    """

    def __init__(self, sku_group=None, **kwargs):
        self.sku_group = None
        self.kind = None
        self.prefix = None
        self.series = None
        self.pattern_code = None
        self.pattern_name = None
        self.core_cable = None
        self.braid_material = None
        self.description = None

        if sku_group:
            self.load(sku_group)

    def __repr__(self):
        if self.sku_group:
            return f"<CableType {self.sku_group} - {self.name()}>"
        return "<CableType (not loaded)>"

    def name(self):
        if not self.series:
            return "Not loaded"
        if self.kind == 'catalog' and self.pattern_name:
            return f"{self.series} {self.pattern_name}"
        if self.description:
            return f"{self.series} — {self.description}"
        return self.series

    def is_loaded(self):
        return self.sku_group is not None

    def load(self, sku_group):
        """Load a sku_group by its identifier.

        Reads (sku, description, archived_at) from sku_group and resolves the
        rest via the YAML resolver (kind, prefix, series, pattern_name,
        core_cable, braid_material).
        """
        from greenlight.cable_config import (
            parse_group_sku, series_data_for_prefix,
        )
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sku, description, archived_at FROM sku_group WHERE sku = %s",
                    (sku_group,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"sku_group {sku_group} not found.")

                self.sku_group = row[0]
                self.description = row[1]
                self.archived_at = row[2]

                parsed = parse_group_sku(self.sku_group)
                self.kind = parsed.get('kind')
                self.prefix = parsed.get('prefix')
                self.series = parsed.get('series')
                self.pattern_code = parsed.get('pattern_code')
                self.pattern_name = parsed.get('pattern_name')

                series_data = series_data_for_prefix(self.prefix) if self.prefix else None
                if series_data:
                    self.core_cable = series_data.get('core_cable')
                    self.braid_material = series_data.get('braid_material')
                else:
                    self.core_cable = None
                    self.braid_material = None
        finally:
            pg_pool.putconn(conn)


# Backward-compat shim: old name still imported in some places.
def find_cable_by_attributes(series, color_pattern, length, connector_type):
    """Deprecated. Use resolve_catalog_variant — Phase 4 returns a
    (sku_group, length, connector_code) tuple instead of a single SKU."""
    result = resolve_catalog_variant(series, color_pattern, length, connector_type)
    return result['sku_group'] if result else None


