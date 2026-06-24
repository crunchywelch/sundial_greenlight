"""Inventory dashboard, series heatmap, and production suggestion screens."""

from collections import defaultdict

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.console import Group

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.db import (
    get_sku_stock_summary, get_recent_sales, get_misc_summary,
    list_ltd_editions, get_cables_for_ltd_sku,
)
from greenlight import shopify_client
from greenlight.product_lines import (
    PREFIX_MAP, LOW_STOCK_THRESHOLD,
    load_yaml_skus, build_sku, get_cost,
)

# Ordered list of prefixes for numbered menu
SERIES_ORDER = ["SC", "SV", "TC", "TV"]


def _avail_style(n):
    """Return Rich style string for an availability count."""
    if n == 0:
        return "bold red"
    elif n <= 5:
        return "yellow"
    return "green"


class InventoryDashboardScreen(Screen):
    """Top-level inventory summary — one row per series."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        yaml_lines = load_yaml_skus()
        sku_counts = get_sku_stock_summary()
        misc = get_misc_summary()

        table = Table(title="Inventory Dashboard", show_header=True, header_style="bold cyan",
                      padding=(0, 1))
        table.add_column("#", justify="right", style="green", width=3)
        table.add_column("Series", width=24)
        table.add_column("Avail", justify="right", width=7)
        table.add_column("Sold", justify="right", width=7)
        table.add_column("Fail", justify="right", width=7)
        table.add_column("Total", justify="right", width=7)
        table.add_column("Coverage", justify="right", width=9)

        grand_avail = 0
        grand_sold = 0
        grand_fail = 0
        grand_total = 0

        for idx, prefix in enumerate(SERIES_ORDER, 1):
            line = yaml_lines.get(prefix)
            if not line:
                continue
            name = f"{line['name']} ({prefix})"

            s_avail = 0
            s_sold = 0
            s_fail = 0
            s_total = 0
            skus_with_stock = 0
            total_skus = 0

            for length in line["lengths"]:
                for pattern in line["patterns"]:
                    for conn in line["connectors"]:
                        sku = build_sku(prefix, length, pattern["code"], conn["code"])
                        total_skus += 1
                        c = sku_counts.get(sku, {})
                        avail = c.get("available", 0)
                        s_avail += avail
                        s_sold += c.get("sold", 0)
                        s_fail += c.get("failed", 0)
                        s_total += c.get("total", 0)
                        if avail > 0:
                            skus_with_stock += 1

            grand_avail += s_avail
            grand_sold += s_sold
            grand_fail += s_fail
            grand_total += s_total

            avail_text = Text(str(s_avail), style=_avail_style(s_avail))
            coverage = f"{skus_with_stock}/{total_skus}"

            table.add_row(
                str(idx), name, avail_text,
                str(s_sold) if s_sold else "-",
                str(s_fail) if s_fail else "-",
                str(s_total),
                coverage,
            )

        # Separator
        table.add_section()

        # Grand total row
        table.add_row(
            "", "[bold]TOTAL[/bold]",
            Text(str(grand_avail), style="bold"),
            str(grand_sold) if grand_sold else "-",
            str(grand_fail) if grand_fail else "-",
            f"[bold]{grand_total}[/bold]",
            "",
        )

        # Special baby row
        misc_avail = sum(v["available"] for v in misc.values())
        misc_sold = sum(v["sold"] for v in misc.values())
        misc_total = sum(v["total"] for v in misc.values())
        if misc_total > 0:
            table.add_row(
                "", "[dim]Special Baby[/dim]",
                Text(str(misc_avail), style=_avail_style(misc_avail)),
                str(misc_sold) if misc_sold else "-",
                "",
                str(misc_total),
                "",
            )

        footer_text = (
            "[green]1.[/green] Studio (Rayon)   "
            "[green]2.[/green] Tour (Cotton)   "
            "[green]s.[/green] Suggestions   "
            "[green]l.[/green] LTD Editions   "
            "[green]q.[/green] Back"
        )

        self.ui.header(operator)
        self.ui.layout["body"].update(table)
        self.ui.layout["footer"].update(Panel(footer_text, title="Options"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ").strip().lower()

        if choice == "1":
            ctx = self.context.copy()
            ctx["heatmap_group"] = "studio"
            return ScreenResult(NavigationAction.PUSH, SeriesHeatmapScreen, ctx)
        elif choice == "2":
            ctx = self.context.copy()
            ctx["heatmap_group"] = "tour"
            return ScreenResult(NavigationAction.PUSH, SeriesHeatmapScreen, ctx)
        elif choice == "s":
            return ScreenResult(NavigationAction.PUSH, ProductionSuggestionsScreen, self.context)
        elif choice == "l":
            return ScreenResult(NavigationAction.PUSH, LTDEditionListScreen, self.context)
        elif choice == "q":
            return ScreenResult(NavigationAction.POP)

        return ScreenResult(NavigationAction.REPLACE, InventoryDashboardScreen, self.context)


# Heatmap groupings: each entry is (prefix, connector_code)
# Studio series share rayon patterns (GL, SL, PW)
# Tour series share cotton patterns (RS, BU, HP, EH)
HEATMAP_GROUPS = {
    "studio": {
        "title": "Studio (Rayon)",
        "items": [("SC", ""), ("SC", "-R"), ("SV", "")],
    },
    "tour": {
        "title": "Tour (Cotton)",
        "items": [("TC", ""), ("TC", "-R"), ("TV", "")],
    },
}


def _build_heatmap_table(prefix, connector_code, yaml_lines, sku_counts):
    """Build a single heatmap Rich Table for one (series, connector) combo."""
    line = yaml_lines[prefix]
    patterns = line["patterns"]
    lengths = line["lengths"]

    # Find display label for this connector
    conn_display = ""
    for conn in line["connectors"]:
        if conn["code"] == connector_code:
            conn_display = conn["display"]
            break

    title = line["name"]
    if conn_display:
        title += f" ({conn_display})"

    t = Table(title=title, show_header=True, header_style="bold cyan",
              padding=(0, 1), expand=False)
    t.add_column("Len", justify="right")
    for p in patterns:
        t.add_column(p["code"], justify="right")
    t.add_column("TOT", justify="right", style="bold")

    col_totals = defaultdict(int)

    for length in lengths:
        row_vals = []
        row_total = 0
        for pattern in patterns:
            sku = build_sku(prefix, length, pattern["code"], connector_code)
            c = sku_counts.get(sku, {})
            avail = c.get("available", 0)
            row_total += avail
            col_totals[pattern["code"]] += avail

            if avail == 0:
                row_vals.append(Text("\u00b7", style="dim"))
            else:
                row_vals.append(Text(str(avail), style=_avail_style(avail)))

        t.add_row(f"{length}ft", *row_vals, str(row_total))

    # Column totals
    t.add_section()
    total_cells = []
    grand = 0
    for p in patterns:
        ct = col_totals[p["code"]]
        grand += ct
        total_cells.append(Text(str(ct), style="bold"))
    t.add_row("[bold]TOTAL[/bold]", *total_cells, f"[bold]{grand}[/bold]")

    return t


class SeriesHeatmapScreen(Screen):
    """Length x pattern heatmap grid — one screen per fabric family."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        group_key = self.context.get("heatmap_group", "studio")

        yaml_lines = load_yaml_skus()
        sku_counts = get_sku_stock_summary()

        group = HEATMAP_GROUPS.get(group_key, HEATMAP_GROUPS["studio"])
        tables = [
            _build_heatmap_table(prefix, conn_code, yaml_lines, sku_counts)
            for prefix, conn_code in group["items"]
        ]

        body = Columns(tables, padding=(0, 2))

        self.ui.header(operator)
        self.ui.layout["body"].update(body)
        self.ui.layout["footer"].update(
            Panel("[green]q.[/green] Back to dashboard", title=group["title"])
        )
        self.ui.render()

        self.ui.wait_back()
        return ScreenResult(NavigationAction.POP)


class ProductionSuggestionsScreen(Screen):
    """Ranked production priority list."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        yaml_lines = load_yaml_skus()
        sku_counts = get_sku_stock_summary()
        recent_90 = get_recent_sales(days=90)
        recent_30 = get_recent_sales(days=30)

        suggestions = []

        for prefix in sorted(yaml_lines.keys()):
            line = yaml_lines[prefix]
            for length in line["lengths"]:
                for pattern in line["patterns"]:
                    for conn in line["connectors"]:
                        sku = build_sku(prefix, length, pattern["code"], conn["code"])
                        c = sku_counts.get(sku, {"total": 0, "available": 0, "sold": 0, "failed": 0})
                        avail = c.get("available", 0)
                        sold = c.get("sold", 0)
                        sales_90 = recent_90.get(sku, 0)
                        sales_30 = recent_30.get(sku, 0)
                        cost = get_cost(line, length, conn["code"])
                        price = line["pricing"].get(length, 0)

                        if avail > LOW_STOCK_THRESHOLD:
                            continue

                        score = 0
                        if avail == 0 and sold > 0:
                            score += 50
                        elif avail == 0 and sold == 0:
                            score += 5
                        elif avail > 0:
                            score += 20

                        if sales_30 > 0:
                            score += sales_30 * 15
                        elif sales_90 > 0:
                            score += sales_90 * 5

                        if price and cost:
                            margin = price - cost
                            score += margin * 0.1

                        if score < 5:
                            continue

                        suggestions.append({
                            "sku": sku,
                            "available": avail,
                            "sold": sold,
                            "sales_30": sales_30,
                            "sales_90": sales_90,
                            "score": score,
                            "margin": (price - cost) if price and cost else None,
                        })

        suggestions.sort(key=lambda x: x["score"], reverse=True)

        high = [s for s in suggestions if s["score"] >= 50][:8]
        medium = [s for s in suggestions if 15 <= s["score"] < 50][:8]
        low = [s for s in suggestions if 5 <= s["score"] < 15][:8]

        table = Table(title="Production Suggestions", show_header=True,
                      header_style="bold cyan", padding=(0, 1))
        table.add_column("Pri", width=4)
        table.add_column("SKU", width=16)
        table.add_column("Avail", justify="right", width=6)
        table.add_column("Sold", justify="right", width=6)
        table.add_column("30d", justify="right", width=5)
        table.add_column("90d", justify="right", width=5)
        table.add_column("Margin", justify="right", width=8)

        def _add_tier(items, label, pri_marker):
            if not items:
                return
            table.add_section()
            table.add_row(f"[bold]{label}[/bold]", "", "", "", "", "", "")
            for s in items:
                margin_str = f"${s['margin']:.0f}" if s["margin"] is not None else "-"
                avail_text = Text(str(s["available"]), style=_avail_style(s["available"]))
                table.add_row(
                    pri_marker,
                    s["sku"],
                    avail_text,
                    str(s["sold"]) if s["sold"] else "-",
                    str(s["sales_30"]) if s["sales_30"] else "-",
                    str(s["sales_90"]) if s["sales_90"] else "-",
                    margin_str,
                )

        _add_tier(high, "HIGH", "[bold red]!![/bold red]")
        _add_tier(medium, "MED", "[yellow]![/yellow]")
        _add_tier(low, "LOW", "[dim].[/dim]")

        if not high and not medium and not low:
            table.add_row("", "[green]All SKUs well-stocked[/green]", "", "", "", "", "")

        self.ui.header(operator)
        self.ui.layout["body"].update(table)
        self.ui.layout["footer"].update(
            Panel("[green]q.[/green] Back to dashboard", title="Options")
        )
        self.ui.render()

        self.ui.wait_back()
        return ScreenResult(NavigationAction.POP)


class LTDEditionListScreen(Screen):
    """List LTD editions; pick one to see its cables and assignments."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        # Show every edition (including archived) — viewing past runs and who
        # owns those cables is a legitimate reason to be here.
        editions = list_ltd_editions(active_only=False)

        table = Table(title="LTD Editions", show_header=True, header_style="bold cyan",
                      padding=(0, 1))
        table.add_column("#", justify="right", style="green", width=3)
        table.add_column("Edition", width=28)
        table.add_column("SKU", width=20)
        table.add_column("Cables", justify="right", width=7)
        table.add_column("Status", width=10)

        for idx, ed in enumerate(editions, 1):
            ed_name = ed.get("description") or ed["slug"]
            status = "[green]active[/green]" if ed["active"] else "[dim]archived[/dim]"
            row_style = None if ed["active"] else "dim"
            table.add_row(
                str(idx), ed_name, ed["sku"], str(ed["cable_count"]), status,
                style=row_style,
            )

        if not editions:
            table.add_row("", "[dim]No LTD editions found[/dim]", "", "", "")

        self.ui.header(operator)
        self.ui.layout["body"].update(table)
        self.ui.layout["footer"].update(
            Panel("Enter a [green]number[/green] to view cables   "
                  "[green]q.[/green] Back", title="Options")
        )
        self.ui.render()

        choice = self.ui.console.input("Choose: ").strip().lower()
        if choice in ("q", ""):
            return ScreenResult(NavigationAction.POP)

        if choice.isdigit():
            n = int(choice)
            if 1 <= n <= len(editions):
                ctx = self.context.copy()
                ctx["ltd_edition"] = editions[n - 1]
                return ScreenResult(NavigationAction.PUSH, LTDEditionCablesScreen, ctx)

        return ScreenResult(NavigationAction.REPLACE, LTDEditionListScreen, self.context)


class LTDEditionCablesScreen(Screen):
    """Show all cables of one LTD edition and who each is assigned to."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        edition = self.context.get("ltd_edition", {})
        sku = edition.get("sku", "")
        name = edition.get("description") or edition.get("slug") or sku

        cables = get_cables_for_ltd_sku(sku)

        # Cache customer lookups — an edition often has several cables going to
        # the same person, and each lookup is a Shopify API round-trip. Names
        # resolve lazily, so only the cables on the current page are fetched.
        name_cache = {}

        def resolve_customer(gid):
            if not gid:
                return "[dim]— unassigned[/dim]"
            if gid not in name_cache:
                customer = shopify_client.get_customer_by_id(gid)
                name_cache[gid] = (customer or {}).get("displayName") or "[red]Unknown[/red]"
            return name_cache[gid]

        assigned_count = sum(1 for c in cables if c.get("shopify_gid"))

        def build_page(page_cables, page_index, total_pages):
            title = f"LTD — {name}"
            if total_pages > 1:
                title += f"  (page {page_index + 1}/{total_pages})"
            table = Table(title=title, show_header=True, header_style="bold cyan",
                          padding=(0, 1))
            # '#' is the per-page row number used by the assign prompt below.
            table.add_column("#", justify="right", style="green", width=3)
            table.add_column("Serial", width=12)
            table.add_column("Variant SKU", width=20)
            table.add_column("QC", justify="center", width=4)
            table.add_column("Assigned To", width=26)

            if not cables:
                table.add_row("", "[dim]No cables registered for this edition[/dim]", "", "", "")
                return table

            for i, cable in enumerate(page_cables, 1):
                test_passed = cable.get("test_passed")
                if test_passed is True:
                    qc = "[green]✓[/green]"
                elif test_passed is False:
                    qc = "[red]✗[/red]"
                else:
                    qc = "[dim]-[/dim]"
                # Surface a non-standard connector finish (custom/LTD builds)
                # right on the SKU cell so it's visible at a glance.
                sku_cell = cable.get("variant_sku") or ""
                finish = cable.get("connector_finish_display")
                if finish:
                    sku_cell += f"  [dim]({finish})[/dim]"
                table.add_row(
                    str(i),
                    cable.get("serial_number") or "",
                    sku_cell,
                    qc,
                    resolve_customer(cable.get("shopify_gid")),
                )
            return table

        self.ui.header(operator)
        hint = f"[cyan]{len(cables)}[/cyan] cable(s), [cyan]{assigned_count}[/cyan] assigned"
        actions = {"a": "Assign cable"} if cables else None
        # Resume on whatever page we were on before an assignment round-trip, so
        # assigning several cables off a later page doesn't bounce back to page 1.
        start_page = self.context.get("ltd_page", 0)
        result = self.ui.paginate(cables, build_page, footer_hint=hint,
                                  actions=actions, start_page=start_page)

        if not result:
            return ScreenResult(NavigationAction.POP)

        # 'a' pressed — pick which cable on the page in view to assign, then
        # hand off to the existing customer-lookup flow. assign_return_to brings
        # the flow back here (instead of the cable scan screen) when it's done,
        # and ltd_page makes it re-open on the same page.
        page_cables = result["page_items"]
        self.context["ltd_page"] = result["page"]
        self.ui.layout["footer"].update(Panel(
            "Enter the [green]#[/green] of the cable to assign "
            "(or [green]Enter[/green] to cancel)",
            title="Assign Cable",
        ))
        self.ui.render()
        try:
            choice = self.ui.console.input("Assign #: ").strip()
        except KeyboardInterrupt:
            choice = ""

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(page_cables):
                cable = page_cables[idx]
                ctx = self.context.copy()
                ctx["assign_cable_serial"] = cable.get("serial_number")
                ctx["assign_cable_sku"] = cable.get("variant_sku")
                ctx["assign_return_to"] = LTDEditionCablesScreen
                from greenlight.screens.orders import CustomerLookupScreen
                return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, ctx)

        # Cancelled or invalid number — redraw, staying on the same page.
        return ScreenResult(NavigationAction.REPLACE, LTDEditionCablesScreen, self.context)
