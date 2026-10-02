"""Intake cable-type selection: series → pattern/MISC/LTD → length → connector."""

import logging
import readline
import sys
import time

from rich.panel import Panel

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import APP_NAME, EXIT_MESSAGE
from greenlight.cable_catalog import (
    CableType, get_distinct_series, get_distinct_color_patterns,
    get_distinct_lengths, resolve_catalog_variant,
)

logger = logging.getLogger(__name__)


# Context keys set by the intake selection flow (series → ... → scan)
_INTAKE_SELECTION_KEYS = (
    "selected_color_pattern", "selected_length", "selected_connector",
    "connector_code", "connector_finish", "cable_type",
)


class SeriesSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        series_options = get_distinct_series()

        if not series_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No series found in database", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Display-friendly names for series
        series_display = {
            "Studio Classic": "Rayon Instrument (Studio Classic)",
            "Studio Vocal Classic": "Rayon XLR (Studio Vocal Classic)",
            "Tour Classic": "Cotton Instrument (Tour Classic)",
            "Tour Vocal Classic": "Cotton XLR (Tour Vocal Classic)",
        }

        # Create menu items — series only. Special Baby (MISC) and Limited
        # Edition (LTD) live one step deeper, alongside the standard patterns
        # for the chosen series.
        menu_items = [series_display.get(s, s) for s in series_options]
        menu_items.append("Back (q)")

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Select the cable series", title="Step 1: Series Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Series"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ")
        except KeyboardInterrupt:
            print(f"\n\n🛑 Exiting {APP_NAME}...")
            print(EXIT_MESSAGE)
            sys.exit(0)

        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)

        # Handle series selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(series_options):
                selected_series = series_options[choice_idx]
                new_context = self.context.copy()
                # Drop selections left over from a previous intake so a stale
                # cable_type can't make the catalog flow look like MISC/LTD
                for key in _INTAKE_SELECTION_KEYS:
                    new_context.pop(key, None)
                new_context["selected_series"] = selected_series
                # Always go to attribute selection (color pattern)
                return ScreenResult(NavigationAction.REPLACE, ColorPatternSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice - brief feedback, then re-display
        self.ui.console.print("[red]Invalid choice[/red]")
        import time; time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, SeriesSelectionScreen, self.context)


class LtdEditionPickerScreen(Screen):
    """Pick an active LTD edition to scan cables against.

    LTD edition CRUD lives in the Shopify app; this screen is read-only and
    just lets the operator pick which existing edition they're scanning for.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        from greenlight.db import list_ltd_editions
        from greenlight.cable_config import prefix_for_series

        # LTD editions are series-agnostic (Phase 5): the series picked
        # earlier in the flow only drives the per-cable prefix attached at
        # registration. Show every active edition here.
        series_prefix = prefix_for_series(selected_series) if selected_series else None
        editions = list_ltd_editions(active_only=True)

        self.ui.header(operator)

        if not editions:
            self.ui.layout["body"].update(Panel(
                "[bold yellow]No active Limited Editions[/bold yellow]\n\n"
                "Create an LTD edition in the Shopify app first, then come back\n"
                "to scan cables against it.",
                title="Limited Edition Picker", border_style="yellow"
            ))
            self.ui.layout["footer"].update(Panel(
                "[green]q.[/green] Back",
                title=""
            ))
            self.ui.render()
            try:
                self.ui.wait_back()
            except KeyboardInterrupt:
                pass
            return ScreenResult(NavigationAction.POP)

        # Build the picker list. Phase 4: an LTD edition is just a sku_group +
        # description. Length is per-cable now, captured on the next screen.
        body_lines = [
            "[bold yellow]Active Limited Editions[/bold yellow]\n"
        ]
        for i, ed in enumerate(editions, 1):
            description = ed.get('description') or ed.get('event_name') or '—'
            n_cables = ed.get('cable_count', 0)
            cable_word = '' if n_cables == 1 else 's'
            body_lines.append(
                f"  [green]{i}.[/green] [bold]{ed['slug']}[/bold] — {description}\n"
                f"     {n_cables} cable{cable_word} registered"
            )
        body_lines.append("")
        body_lines.append("  [green]Q[/green]. Back")

        self.ui.layout["body"].update(Panel(
            "\n".join(body_lines), title="Limited Edition Picker"
        ))
        self.ui.layout["footer"].update(Panel(
            "Pick an edition by number, or 'q' to go back",
            title="Choose"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice in ('q', ''):
            return ScreenResult(NavigationAction.POP)

        try:
            idx = int(choice) - 1
        except ValueError:
            self.ui.console.print("[red]Invalid choice[/red]")
            time.sleep(0.5)
            return ScreenResult(NavigationAction.REPLACE, LtdEditionPickerScreen, self.context)

        if 0 <= idx < len(editions):
            selected_sku = editions[idx]['sku']
            # Phase 5: LTD group SKU is series-agnostic ('LTD-PHISH26'), so
            # CableType needs the prefix passed in from screen context.
            try:
                cable_type = CableType()
                cable_type.load(selected_sku, prefix=series_prefix)
            except ValueError as e:
                self.ui.layout["body"].update(Panel(
                    f"❌ Error loading SKU {selected_sku}: {e}",
                    title="Error", style="red"
                ))
                self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
                self.ui.render()
                self.ui.wait_back()
                return ScreenResult(NavigationAction.POP)

            new_context = self.context.copy()
            new_context["cable_type"] = cable_type
            # LTD/MISC variants need length + connector entered per-cable.
            return ScreenResult(NavigationAction.REPLACE, VariantLengthEntryScreen, new_context)

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, LtdEditionPickerScreen, self.context)


SPECIAL_BABY_OPTION = "Special Baby (MISC)"
LIMITED_EDITION_OPTION = "Limited Edition (LTD)"


class ColorPatternSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        color_options = get_distinct_color_patterns(selected_series)

        if not color_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(f"No color patterns found for {selected_series}", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Append specialty entries after the standard patterns. They route to
        # different downstream screens but live alongside the patterns from
        # the operator's perspective — the choice is "what kind of cable am
        # I scanning today?"
        menu_items = list(color_options)
        menu_items.append(SPECIAL_BABY_OPTION)
        menu_items.append(LIMITED_EDITION_OPTION)
        menu_items.append("Back (q)")

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(f"Series: {selected_series}\nSelect the color/pattern", title="Step 2: Color Pattern Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Colors"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")

        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)

        # Handle selection
        try:
            choice_idx = int(choice) - 1
            if not (0 <= choice_idx < len(menu_items) - 1):
                raise ValueError
            selected = menu_items[choice_idx]
            new_context = self.context.copy()

            if selected == SPECIAL_BABY_OPTION:
                return ScreenResult(NavigationAction.REPLACE, MiscVariantPickerScreen, new_context)
            if selected == LIMITED_EDITION_OPTION:
                return ScreenResult(NavigationAction.REPLACE, LtdEditionPickerScreen, new_context)

            # Standard pattern → length selection
            new_context["selected_color_pattern"] = selected
            return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice - brief feedback, then re-display
        self.ui.console.print("[red]Invalid choice[/red]")
        import time; time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, ColorPatternSelectionScreen, self.context)


SERIES_PREFIX_MAP = {
    'Studio Classic': 'SC',
    'Studio Patch': 'SP',
    'Studio Vocal Classic': 'SV',
    'Tour Classic': 'TC',
    'Tour Vocal Classic': 'TV',
}


def _format_length(length):
    """Render a length value as e.g. '10ft' or '10.5ft'."""
    try:
        val = float(length)
    except (TypeError, ValueError):
        return str(length) if length is not None else ""
    return f"{int(val)}ft" if val == int(val) else f"{val}ft"


class MiscVariantPickerScreen(Screen):
    """Pick an existing MISC variant for the selected series, or create a new one."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        series_prefix = SERIES_PREFIX_MAP.get(selected_series)

        if not series_prefix:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"❌ Unknown series: {selected_series}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        from greenlight.db import search_misc_variants
        existing = search_misc_variants(series_prefix)

        body_lines = [
            f"[bold yellow]Miscellaneous Cable — {selected_series}[/bold yellow]\n",
        ]
        if existing:
            body_lines.append("Existing MISC variants for this series:\n")
        else:
            body_lines.append("No existing MISC variants for this series yet.\n")

        menu_items = []
        for v in existing:
            n_cables = v.get('cable_count', 0)
            cable_word = '' if n_cables == 1 else 's'
            length = v.get('length')
            length_part = f"{_format_length(length)}, " if length is not None else ""
            label = f"{v['sku']}  ({length_part}{n_cables} cable{cable_word})  {v['description']}"
            menu_items.append(label)
        menu_items.append("[N] New MISC variant")
        menu_items.append("[Q] Back")

        rows = [
            f"[green]{i + 1}.[/green] {name}" if i < len(existing)
            else f"[green]{name}[/green]"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "\n".join(body_lines), title="Step 3: MISC Variant"
        ))
        self.ui.layout["footer"].update(Panel(
            "\n".join(rows),
            title="Pick a variant or press 'N' to create a new one"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice in ('q', ''):
            return ScreenResult(NavigationAction.POP)

        if choice == 'n':
            return ScreenResult(NavigationAction.REPLACE, MiscVariantCreateScreen, self.context)

        try:
            idx = int(choice) - 1
        except ValueError:
            self.ui.console.print("[red]Invalid choice[/red]")
            time.sleep(0.5)
            return ScreenResult(NavigationAction.REPLACE, MiscVariantPickerScreen, self.context)

        if 0 <= idx < len(existing):
            selected = existing[idx]
            try:
                cable_type = CableType()
                cable_type.load(selected['sku'])
            except ValueError as e:
                self.ui.layout["body"].update(Panel(
                    f"❌ Error loading SKU {selected['sku']}: {e}",
                    title="Error", style="red"
                ))
                self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
                self.ui.render()
                self.ui.wait_back()
                return ScreenResult(NavigationAction.POP)

            # MISC groups are single-length; the picker shows that length and
            # the operator's selection commits to it. Skip the length entry
            # screen entirely.
            if selected.get('length') is None:
                # Empty group (no cables yet) — fall through to the length
                # prompt so the operator establishes the group's length.
                new_context = self.context.copy()
                new_context["cable_type"] = cable_type
                return ScreenResult(NavigationAction.REPLACE, VariantLengthEntryScreen, new_context)

            new_context = self.context.copy()
            new_context["cable_type"] = cable_type
            new_context["selected_length"] = selected['length']
            return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, MiscVariantPickerScreen, self.context)


class MiscVariantCreateScreen(Screen):
    """Create a new MISC variant: prompt for description, then length.

    Each MISC sku_group holds cables of a single length, so length is part
    of group identity (a same-description-different-length combo creates a
    new group). Operator commits to both up front.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        series_prefix = SERIES_PREFIX_MAP.get(selected_series)

        if not series_prefix:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"❌ Unknown series: {selected_series}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # --- Step 1: description ---
        description = self._prompt_description(operator, selected_series)
        if description is None:
            return ScreenResult(NavigationAction.POP)

        # --- Step 2: length ---
        length_value = self._prompt_length(operator, selected_series, description)
        if length_value is None:
            return ScreenResult(NavigationAction.POP)

        # Resolve or create the MISC sku_group with both keys
        from greenlight.db import get_or_create_misc_sku
        new_sku = get_or_create_misc_sku(series_prefix, description, length_value)
        if not new_sku:
            self.ui.layout["body"].update(Panel(
                "❌ Failed to create MISC variant SKU. Check logs.",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        try:
            cable_type = CableType()
            cable_type.load(new_sku)
        except ValueError as e:
            self.ui.layout["body"].update(Panel(
                f"❌ Error loading new SKU {new_sku}: {e}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        new_context = self.context.copy()
        new_context["cable_type"] = cable_type
        new_context["selected_length"] = length_value
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)

    def _prompt_description(self, operator, selected_series):
        max_desc_len = 90
        prefill_text = None
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]New MISC variant — {selected_series}[/bold yellow]\n\n"
            "[bold cyan]Step 1: enter a description for this variant:[/bold cyan]\n"
            "[dim](Length is the next step — don't include it here)[/dim]\n\n"
            "Include details like:\n"
            "  • Color/pattern (e.g., 'custom blue/orange')\n"
            "  • Connector types (e.g., 'Neutrik TS-TRS')\n"
            "  • Cable construction (e.g., 'cotton braid')\n"
            "  • Any special attributes\n\n"
            "Example: 'dark putty houndstooth with gold connectors instead of nickel'",
            title="MISC Variant — Description", border_style="yellow"
        ))

        try:
            while True:
                if prefill_text:
                    self.ui.layout["footer"].update(Panel(
                        f"[red]Too long ({len(prefill_text)}/{max_desc_len} chars) — please shorten:[/red]",
                        title="Description"
                    ))
                else:
                    self.ui.layout["footer"].update(Panel(
                        f"Enter description (max {max_desc_len} chars) or 'q' to cancel",
                        title="Description"
                    ))
                self.ui.render()

                if prefill_text:
                    readline.set_startup_hook(lambda: readline.insert_text(prefill_text))
                else:
                    readline.set_startup_hook(None)

                try:
                    description = self.ui.console.input("Description: ").strip()
                finally:
                    readline.set_startup_hook(None)

                if description.lower() == 'q' or not description:
                    return None

                if len(description) <= max_desc_len:
                    return description
                prefill_text = description
        except KeyboardInterrupt:
            return None

    def _prompt_length(self, operator, selected_series, description):
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]New MISC variant — {selected_series}[/bold yellow]\n"
            f"[dim]Description: {description}[/dim]\n\n"
            "[bold cyan]Step 2: enter cable length in feet[/bold cyan]\n"
            "Examples: 3, 6, 10, 15, 20, 25\n\n"
            "[dim]A MISC group is single-length: same description with a different length will\n"
            "create a separate sku_group.[/dim]",
            title="MISC Variant — Length", border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter length in feet (number only) or 'q' to go back",
            title="Length Entry"
        ))
        self.ui.render()

        try:
            length_input = self.ui.console.input("Length (ft): ").strip()
        except KeyboardInterrupt:
            return None

        if length_input.lower() == 'q' or not length_input:
            return None

        try:
            length_value = float(length_input)
            if length_value <= 0:
                raise ValueError("must be positive")
            return length_value
        except ValueError:
            self.ui.layout["body"].update(Panel(
                f"❌ Invalid length: {length_input}",
                title="Invalid Length", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
            self.ui.render()
            self.ui.console.input()
            return self._prompt_length(operator, selected_series, description)


class VariantLengthEntryScreen(Screen):
    """Free-form length entry for LTD cables (and the rare empty MISC group).

    LTD editions allow per-cable length so each scan goes through here.
    MISC groups are single-length — MiscVariantCreateScreen captures length
    upfront, and the picker auto-fills the existing group's length. The one
    case that still routes here for MISC is selecting an orphan empty group
    (no cables yet, length unknown) — the operator establishes the length
    on this screen.

    Catalog cables don't reach this screen — they use LengthSelectionScreen
    (YAML-driven list of standard lengths).
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        if cable_type is None or not cable_type.is_loaded():
            return ScreenResult(NavigationAction.POP)

        scope = cable_type.name()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]Enter cable length — {scope}[/bold yellow]\n\n"
            "[bold cyan]Length in feet[/bold cyan]\n"
            "Examples: 3, 6, 10, 15, 20, 25\n\n"
            "[dim]This length is stored on this specific cable only.[/dim]",
            title="Variant — Length", border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter length in feet (number only) or 'q' to go back",
            title="Length Entry"
        ))
        self.ui.render()

        try:
            length_input = self.ui.console.input("Length (ft): ").strip()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if length_input.lower() == 'q' or not length_input:
            return ScreenResult(NavigationAction.POP)

        try:
            length_value = float(length_input)
            if length_value <= 0:
                raise ValueError("must be positive")
        except ValueError:
            self.ui.layout["body"].update(Panel(
                f"❌ Invalid length: {length_input}",
                title="Invalid Length", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, VariantLengthEntryScreen, self.context)

        new_context = self.context.copy()
        new_context["selected_length"] = length_value
        # Reuse ConnectorTypeSelectionScreen for the connector pick — it
        # detects the variant flow via cable_type in context.
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)


class LengthSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        selected_color = self.context.get("selected_color_pattern")
        length_options = get_distinct_lengths(selected_series, selected_color)

        if not length_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(f"No lengths found for {selected_series} {selected_color}", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Create menu items
        menu_items = [f"{length} ft" for length in length_options]
        menu_items.append("Back (q)")

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(f"Series: {selected_series}\nColor: {selected_color}\nSelect the cable length", title="Step 3: Length Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Lengths"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")

        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)

        # Handle length selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(length_options):
                selected_length = length_options[choice_idx]
                new_context = self.context.copy()
                new_context["selected_length"] = selected_length
                # Always go through connector selection — it handles the
                # auto-skip case for single-connector series internally.
                return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice - brief feedback, then re-display
        self.ui.console.print("[red]Invalid choice[/red]")
        import time; time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, self.context)


class ConnectorTypeSelectionScreen(Screen):
    """Pick a connector type. Handles both catalog and variant (MISC/LTD) flows.

    Catalog: came via series → pattern → length, no cable_type in context.
        Resolves (sku_group, length, connector_code) via resolve_catalog_variant
        at exit and routes to scan.

    Variant (MISC/LTD): came via picker → length entry, cable_type already in
        context. Just captures connector_code and routes to scan.
    """

    def run(self) -> ScreenResult:
        from greenlight.cable_config import (
            series_data_for_prefix, prefix_for_series, connector_display_for,
        )
        operator = self.context.get("operator", "")
        selected_length = self.context.get("selected_length")
        cable_type = self.context.get("cable_type")
        is_variant_flow = cable_type is not None and cable_type.is_loaded()

        # Determine the prefix to use for the connector list.
        if is_variant_flow:
            prefix = cable_type.prefix
            series_label = cable_type.series or prefix
            color_label = None
        else:
            selected_series = self.context.get("selected_series")
            selected_color = self.context.get("selected_color_pattern")
            prefix = prefix_for_series(selected_series)
            series_label = selected_series
            color_label = selected_color

        series_data = series_data_for_prefix(prefix) if prefix else None
        connectors = (series_data or {}).get('connectors') or []
        # Sort straight (code='') before right-angle (code='-R')
        connectors = sorted(connectors, key=lambda c: ((c.get('code') or '').startswith('-R'), c.get('display') or ''))

        if not connectors:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "No connector types found for the selected series",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Auto-skip if there's only one connector option (e.g. vocal series).
        if len(connectors) == 1:
            return self._finish(connectors[0], cable_type, is_variant_flow)

        menu_items = [c.get('display') or '?' for c in connectors]
        menu_items.append("Back (q)")
        rows = [f"[green]{i + 1}.[/green] {name}" for i, name in enumerate(menu_items)]

        body_lines = [f"Series: {series_label}"]
        if color_label:
            body_lines.append(f"Color: {color_label}")
        body_lines.append(f"Length: {selected_length} ft")
        body_lines.append("Select connector type")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "\n".join(body_lines), title="Step 4: Connector Selection"
        ))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Connectors"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)

        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(connectors):
                return self._finish(connectors[choice_idx], cable_type, is_variant_flow)
        except ValueError:
            pass

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, self.context)

    def _finish(self, connector_dict, cable_type, is_variant_flow):
        """Capture the chosen connector and route to scan. Resolves the
        sku_group at exit for catalog flow."""
        connector_code = connector_dict.get('code') or ''
        connector_display = connector_dict.get('display') or ''
        new_context = self.context.copy()
        new_context['selected_connector'] = connector_display
        new_context['connector_code'] = connector_code

        if is_variant_flow:
            # MISC/LTD: cable_type already in context (the sku_group). Custom
            # builds can use any connector finish, so for XLR capture it (it
            # drives the shell-bond test) before scanning. Non-XLR variants go
            # straight to scanning.
            if 'XLR' in (connector_display or '').upper():
                return ScreenResult(NavigationAction.REPLACE, ConnectorFinishSelectionScreen, new_context)
            from greenlight.screens.cable.intake_scan import ScanCableIntakeScreen
            return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)

        # Catalog: resolve to (sku_group, length, connector_code) and load
        # the CableType from sku_group.
        selected_series = self.context.get("selected_series")
        selected_color = self.context.get("selected_color_pattern")
        selected_length = self.context.get("selected_length")
        result = resolve_catalog_variant(
            selected_series, selected_color, selected_length, connector_display,
        )
        if not result:
            self.ui.layout["body"].update(Panel(
                "Could not resolve a SKU for the selected attributes",
                title="Error", style="red",
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Phase 5: catalog group SKU is just a pattern code (e.g. 'GL') with
        # no prefix. resolve_catalog_variant returns prefix separately; thread
        # it into CableType so it can resolve series/connectors.
        try:
            new_cable_type = CableType()
            new_cable_type.load(result['sku_group'], prefix=result['prefix'])
        except ValueError as e:
            self.ui.layout["body"].update(Panel(
                f"Error loading sku_group: {e}", title="Error", style="red",
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        new_context['cable_type'] = new_cable_type
        new_context['selected_length'] = result['length']
        new_context['connector_code'] = result['connector_code']
        from greenlight.screens.cable.intake_scan import ScanCableIntakeScreen
        return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)


class ConnectorFinishSelectionScreen(Screen):
    """Pick the connector finish for a custom (MISC) or LTD XLR build.

    Only reached from the variant flow for XLR connectors. The chosen finish is
    stored per-cable and decides whether the XLR shell-bond test (XSHELL) runs —
    black/gold Neutrik shells are non-conductive by design and must skip it.
    Standard catalog cables never reach here; their finish is implied by the
    series (cotton→nickel, rayon→black).
    """

    # Nickel first so pressing Enter accepts the common default.
    FINISH_ORDER = ['nickel', 'black_gold']

    def run(self) -> ScreenResult:
        from greenlight.cable_config import CONNECTOR_FINISHES
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        selected_length = self.context.get("selected_length")
        connector_display = self.context.get("selected_connector") or "XLR–XLR"

        finishes = [(code, CONNECTOR_FINISHES[code]['display'])
                    for code in self.FINISH_ORDER if code in CONNECTOR_FINISHES]
        menu_items = [disp for _, disp in finishes]
        menu_items.append("Back (q)")
        rows = [f"[green]{i + 1}.[/green] {name}" for i, name in enumerate(menu_items)]

        body_lines = []
        if cable_type:
            body_lines.append(cable_type.name())
        body_lines.append(f"Connector: {connector_display}")
        if selected_length is not None:
            body_lines.append(f"Length: {_format_length(selected_length)}")
        body_lines.append("\nSelect the connector finish for this run")
        body_lines.append(
            "[dim]Black/Gold (Neutrik) shells are non-conductive — the shell-bond "
            "test is skipped for them.[/dim]"
        )

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("\n".join(body_lines), title="Connector Finish"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Finishes"))
        self.ui.render()

        choice = self.ui.console.input("Choose (Enter = Nickel): ").strip().lower()

        # Enter accepts the default (first finish = nickel).
        if choice == "":
            return self._finish(finishes[0][0])
        if choice == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(finishes):
                return self._finish(finishes[idx][0])
        except ValueError:
            pass

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, ConnectorFinishSelectionScreen, self.context)

    def _finish(self, finish_code):
        new_context = self.context.copy()
        new_context['connector_finish'] = finish_code
        from greenlight.screens.cable.intake_scan import ScanCableIntakeScreen
        return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)
