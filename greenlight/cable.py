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
    """Fetch all SKUs from the database"""
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT sku FROM cable_skus ORDER BY sku")
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


def find_cable_by_attributes(series, color_pattern, length, connector_type):
    """Find the catalog SKU matching (series, color_pattern, length, connector).

    Constructs the SKU from YAML lookups (prefix from series, code from
    pattern_name, code from connector display string) and verifies it exists
    in cable_skus before returning it. Returns None if any lookup fails or
    the SKU isn't registered.
    """
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

    # Length comes in as a string like '12' or '06' from the screens.
    sku = f"{prefix}-{length}{pattern_code}{connector_code}"

    # Confirm the SKU exists in cable_skus (audio_sync_skus generates the
    # full cartesian, but a missing combination would be a config gap).
    conn = pg_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM cable_skus WHERE sku = %s LIMIT 1", (sku,))
            if cur.fetchone():
                return sku
            return None
    except Exception as e:
        print(f"Error verifying cable SKU: {e}")
        return None
    finally:
        pg_pool.putconn(conn)

class CableType:
    def __init__(self, sku=None, **kwargs):
        self.sku = None
        self.series = None
        self.price = None
        self.core_cable = None
        self.braid_material = None
        self.color_pattern = None
        self.length = None
        self.connector_type = None
        self.description = None

        if sku:
            self.load(sku)

    def __repr__(self):
        if self.sku:
            return f"<CableType {self.sku} - {self.name()}>"
        return "<CableType (not loaded)>"

    def name(self):
        if not self.series:
            return "Not loaded"

        # Catalog cables: "Series LengthFt ColorPattern (RA)"
        # MISC/LTD: color_pattern/connector_type are None (kind-driven shape).
        # Fall back to "Series LengthFt — description" for those.
        if self.color_pattern:
            base = f"{self.series} {self.length}ft {self.color_pattern}"
            if self.connector_type and self.connector_type.startswith("RA"):
                base += " (RA)"
            return base

        suffix = self.description or 'variant'
        return f"{self.series} {self.length}ft — {suffix}"

    def load(self, sku):
        """Load cable data by SKU.

        Reads the minimal columns from cable_skus (sku, description, length)
        and resolves series/core_cable/braid_material/color_pattern/connector_type
        via the YAML resolver. After Phase 3.5 drops the soon-to-die columns,
        this function is the only place that needs to change to keep the
        public attribute surface (.series, .color_pattern, etc.) stable.
        """
        from greenlight.db import _enrich_record

        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sku, description, length FROM cable_skus WHERE sku = %s",
                    (sku,),
                )
                row = cur.fetchone()
                if not row:
                    raise ValueError(f"SKU {sku} not found.")

                record = _enrich_record({
                    'sku': row[0],
                    'description': row[1],
                    'length': row[2],
                })

                self.sku = record['sku']
                self.series = record.get('series')
                self.price = None  # not stored on cable_skus; not used by callers today
                self.core_cable = record.get('core_cable')
                self.braid_material = record.get('braid_material')
                self.color_pattern = record.get('color_pattern')
                self.length = record.get('length')
                self.connector_type = record.get('connector_type')
                self.description = record.get('description')
        finally:
            pg_pool.putconn(conn)
    
    def is_loaded(self):
        """Check if cable data has been loaded"""
        return self.sku is not None
    
    def get_display_info(self):
        """Get formatted display information for UI"""
        if not self.is_loaded():
            return "No cable selected"
        
        return f"""SKU: {self.sku}
Name: {self.name()}

Series: {self.series}
Length: {self.length} ft
Color: {self.color_pattern}
Connector: {self.connector_type}
Core Cable: {self.core_cable}
Braid Material: {self.braid_material}
Description: {self.description}"""

class cableUI:
    def __init__(self, ui_base):
        self.ui = ui_base
        self.cable_type = CableType()

    def select_cable(self):
        #CABLE_TYPE_ENUMS = fetch_enum_values("series")
        #CONNECTOR_TYPE_ENUMS = fetch_enum_values("length")
        menu_items = [
            {"label": "Enter SKU", "action": self.select_by_sku},
            {"label": "Select By Attribute", "action": self.select_by_attribute},
        ]
        choice = self.ui.render_footer_menu(menu_items, "Audio Cable Management")
        if choice == "":
            return
        else: 
            return menu_items[choice]["action"]()
        return

    def select_by_sku(self):
        self.ui.layout["footer"].update(Panel("wtf", title="Select by SKU"))
        self.ui.render()
        sku = self.ui.console.input("Enter SKU: ")
        self.cable_type.load(sku)

    def select_by_attribute(self):
        return

    def test_cable(self):
        """Run cable tests using Arduino tester"""
        cable_tester = hardware_manager.get_cable_tester()

        if not cable_tester:
            self.ui.layout["body"].update(Panel(
                "[red]Cable tester not available.[/red]\n\n"
                "Please check that the Arduino is connected.",
                title="Test Error"
            ))
            self.ui.render()
            self.ui.console.input("(press enter to continue)")
            return None

        if not cable_tester.is_ready():
            self.ui.layout["body"].update(Panel(
                "[yellow]Cable tester not ready. Attempting to connect...[/yellow]",
                title="Connecting"
            ))
            self.ui.render()

            if not cable_tester.initialize():
                self.ui.layout["body"].update(Panel(
                    "[red]Failed to connect to cable tester.[/red]\n\n"
                    "Check USB connection and try again.",
                    title="Connection Failed"
                ))
                self.ui.render()
                self.ui.console.input("(press enter to continue)")
                return None

        # Build test results display
        results_table = Table(show_header=True, header_style="bold")
        results_table.add_column("Test", width=20)
        results_table.add_column("Result", width=15)
        results_table.add_column("Details", width=30)

        all_passed = True
        test_data = {}

        # Run continuity test
        self.ui.layout["body"].update(Panel(
            "[cyan]Running continuity test...[/cyan]",
            title="Testing"
        ))
        self.ui.render()

        try:
            cont_result = cable_tester.run_continuity_test()
            test_data['continuity'] = cont_result

            if cont_result.passed:
                results_table.add_row(
                    "Continuity",
                    Text("PASS", style="bold green"),
                    "Tip-Tip OK, Sleeve-Sleeve OK"
                )
            else:
                all_passed = False
                reason_text = cont_result.reason or "Unknown failure"
                reason_display = {
                    "REVERSED": "Polarity reversed (tip/sleeve swapped)",
                    "CROSSED": "Short between tip and sleeve",
                    "NO_CABLE": "No cable detected",
                    "TIP_OPEN": "Tip connection open",
                    "SLEEVE_OPEN": "Sleeve connection open"
                }.get(reason_text, reason_text)

                results_table.add_row(
                    "Continuity",
                    Text("FAIL", style="bold red"),
                    reason_display
                )
        except Exception as e:
            all_passed = False
            results_table.add_row(
                "Continuity",
                Text("ERROR", style="bold yellow"),
                str(e)[:30]
            )

        # Run resistance test
        self.ui.layout["body"].update(Panel(
            "[cyan]Running resistance test...[/cyan]",
            title="Testing"
        ))
        self.ui.render()

        try:
            res_result = cable_tester.run_resistance_test()
            test_data['resistance'] = res_result

            if res_result.passed:
                if res_result.calibrated and res_result.milliohms is not None:
                    details = f"{res_result.milliohms} mOhm"
                else:
                    details = f"ADC: {res_result.adc_value} (uncalibrated)"

                results_table.add_row(
                    "Resistance",
                    Text("PASS", style="bold green"),
                    details
                )
            else:
                all_passed = False
                results_table.add_row(
                    "Resistance",
                    Text("FAIL", style="bold red"),
                    f"High resistance (ADC: {res_result.adc_value})"
                )
        except Exception as e:
            all_passed = False
            results_table.add_row(
                "Resistance",
                Text("ERROR", style="bold yellow"),
                str(e)[:30]
            )

        # Show results
        overall_status = Text("ALL TESTS PASSED", style="bold green") if all_passed else Text("TESTS FAILED", style="bold red")

        result_content = Table.grid()
        result_content.add_row(overall_status)
        result_content.add_row("")
        result_content.add_row(results_table)

        self.ui.layout["body"].update(Panel(result_content, title="Test Results"))
        self.ui.render()

        self.ui.console.input("(press enter to continue)")

        return {
            'passed': all_passed,
            'continuity': test_data.get('continuity'),
            'resistance': test_data.get('resistance')
        }

    def print_cable_tag(self):
        self.coming_soon("Print Cable Tag")
        return

    def print_cable_wrap(self):
        self.coming_soon("Print Cable Wrap")

    def coming_soon(self, title):
        self.ui.layout["footer"].update(Panel("Coming Soon.", title=title))
        self.ui.render()
        while True:
            sku = self.ui.console.input("(press enter to continue)")
            return

    def go(self):
        menu_items = [
            {"label": "Select Cable Type", "action": self.select_cable},
            {"label": "Print Cable Tag", "action": self.print_cable_tag},
            {"label": "Print Cable Wrap", "action": self.print_cable_wrap},
        ]

        choice = self.ui.render_footer_menu(menu_items, "Audio Cable Management")
        if choice == "":
            return
        else: 
            menu_items[choice]["action"]()

        if self.cable_type.sku:
            self.ui.layout["body"].update(Panel("Success", title="Selected Cable Type"))
            menu_items.prepend({"label": "Run Test", "action": self.test_cable})

            choice = self.ui.render_footer_menu(menu_items, "Audio Cable Management")
            if choice == "":
                return
            else: 
                menu_items[choice]["action"]()
        else:
            self.ui.layout["body"].update(Panel("Fail", title="Selected Cable Type"))
            self.ui.render()
            while True:
                x=1
