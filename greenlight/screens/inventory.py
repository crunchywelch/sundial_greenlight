"""Inventory dashboard, series heatmap, and production suggestion screens."""

from collections import defaultdict

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.console import Group

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.db import get_sku_stock_summary, get_recent_sales, get_special_baby_summary
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
        misc = get_special_baby_summary()

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

        self.ui.console.input("Choose: ")
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

        self.ui.console.input("Choose: ")
        return ScreenResult(NavigationAction.POP)
