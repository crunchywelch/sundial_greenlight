"""
Order Label Printing

Prints the box labels for a wholesale order: the UPC label for the box
back, the side label for the spine, and the Prop 65 warning. Side and Prop 65
go to the 1" printer, UPC to the 2".

Reached with `l` from a wholesale order's scan screen (OrderFulfillScanScreen,
via `o`). Website orders don't get box labels.

Registration labels are NOT printed here. Each carries a code for one
physical cable, so the scan screen prints it as that cable is scanned.

Planning lives in greenlight/label_batch.py, which has no printer, DB or
Shopify in it; this screen is the operator's end of it.
"""

import logging

from rich.panel import Panel
from rich.table import Table

from greenlight.label_batch import (
    RETAIL_TEMPLATES, TEMPLATE_LABELS, plan_order,
)
from greenlight.screen_manager import NavigationAction, Screen, ScreenResult

logger = logging.getLogger(__name__)


def _roll_name(stock) -> str:
    """What the operator calls this stock's printer: 1" or 2"."""
    return f'{stock[1] / 25.4:.0f}"'


def draft_lifecycle(order) -> str:
    """Where a draft has got to, in words an operator can act on.

    The lifecycle trips people up: a draft becomes an Order only when it is
    completed -- the buyer paying the invoice, or someone completing it in
    admin -- and only Orders can be fulfilled in Shopify. Packing doesn't
    wait for that, so the `o` list shows drafts too, and says how far each
    has got.
    """
    became = order.get("order")
    if became:
        status = (became.get("displayFulfillmentStatus") or "").replace("_", " ")
        return f"{became.get('name', 'order')} · {status.title() or 'order'}"
    status = (order.get("status") or "").replace("_", " ").title()
    return f"{status} · not an order yet" if status else "not an order yet"


class OrderLabelPrintScreen(Screen):
    """Choose which labels to print for one order, then send each to its printer.

    Which labels is asked rather than fixed: not every retailer takes the UPC
    label, and the Prop 65 warning is only wanted on retail-boxed goods. The
    toggles also make a retry possible: if one printer failed, turn off what
    already printed and print again.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        order = self.context.get("label_order") or {}
        selected = {t: True for t in RETAIL_TEMPLATES}
        upcs = None          # fetched lazily, and only if a UPC label is on
        notice = None

        while True:
            needing_upc = [t for t in RETAIL_TEMPLATES
                           if selected[t] and TEMPLATE_LABELS[t][2]]
            if needing_upc and upcs is None:
                upcs = self._load_upcs(operator)
                notice = None
                if upcs is None:
                    # Turned off, not skipped per SKU: every SKU would say it
                    # has no UPC in Shopify, which isn't what's wrong. Turning
                    # it back on tries Shopify again.
                    for template in needing_upc:
                        selected[template] = False
                    number = RETAIL_TEMPLATES.index(needing_upc[0]) + 1
                    notice = ("[bold red]Can't reach Shopify for UPCs, so the "
                              "UPC label is off.[/bold red] Press "
                              f"[cyan]{number}[/cyan] to try again.")

            templates = [t for t in RETAIL_TEMPLATES if selected[t]]
            plan = plan_order(order.get("line_items"), templates=templates,
                              upc_by_sku=upcs or {})

            self._render(operator, order, selected, plan, notice)

            try:
                choice = self.ui.console.input("Choose: ").strip().lower()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.POP)

            if choice in ("", "q"):
                return ScreenResult(NavigationAction.POP)
            if choice.isdigit() and 1 <= int(choice) <= len(RETAIL_TEMPLATES):
                template = RETAIL_TEMPLATES[int(choice) - 1]
                selected[template] = not selected[template]
                continue
            if choice == "p":
                if not plan.jobs:
                    continue
                self._print(operator, plan)
                return ScreenResult(NavigationAction.POP)

    # -- rendering ------------------------------------------------------

    def _render(self, operator, order, selected, plan, notice=None):
        customer = (order.get("customer") or {}).get("displayName") or "—"
        cables = sum(li["quantity"] for li in order.get("line_items", []))

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="green", width=3)
        table.add_column("", width=3)
        table.add_column("Label", width=12)
        table.add_column("Goes on", style="dim", width=10)
        table.add_column("Stock", style="dim", width=9)
        table.add_column("Labels", justify="right", width=7)

        for i, template in enumerate(RETAIL_TEMPLATES, 1):
            name, where, _needs_upc = TEMPLATE_LABELS[template]
            count = sum(j.quantity for j in plan.jobs
                        if j.template == template)
            on = selected[template]
            table.add_row(
                str(i), "[green]x[/green]" if on else " ", name, where,
                self._stock_label(template),
                str(count) if on else "[dim]—[/dim]",
            )

        summary = f"{plan.label_count} label(s) in {len(plan.jobs)} job(s)"

        body = [
            f"[bold]{order.get('name', '?')}[/bold]   {customer}   "
            f"{cables} cable(s)",
            "",
            summary,
        ]
        for warning in plan.warnings:
            body.append(f"[yellow]! {warning}[/yellow]")

        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            table, title="Labels to Print",
            subtitle="\n".join(body[:1])))
        self.ui.layout["footer"].update(Panel(
            "\n".join([
                *([notice] if notice else []),
                summary,
                *[f"[yellow]! {w}[/yellow]" for w in plan.warnings],
                "",
                f"[cyan]1-{len(RETAIL_TEMPLATES)}[/cyan] = toggle a label | "
                f"[cyan]'p'[/cyan] = print | [cyan]'q'[/cyan] = back",
            ]),
            title="Order Labels", border_style="green"))
        self.ui.render()

    @staticmethod
    def _stock_label(template):
        from greenlight.hardware.tsc_label_printer import stock_for_template
        stock = stock_for_template(template)
        if not stock:
            return "?"
        w, h = stock
        return f'{w / 25.4:.0f}" x {h / 25.4:.0f}"'

    # -- data -----------------------------------------------------------

    def _load_upcs(self, operator):
        """SKU -> UPC in one bulk call, or None if Shopify couldn't be read.
        Shopify's barcode field is the source of truth for retail UPCs."""
        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "[yellow]Loading UPCs from Shopify...[/yellow]",
            title="Order Labels"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()

        from greenlight.shopify_client import get_all_product_skus
        try:
            rows = get_all_product_skus()
        except Exception as e:
            logger.error("Failed to load SKUs for UPCs: %s", e)
            return None
        return {sku: v.get("barcode")
                for sku, v in rows.items() if v.get("barcode")}

    # -- printing -------------------------------------------------------

    def _print(self, operator, plan):
        """Send each stock's jobs to its printer, and report on each.

        One printer failing doesn't stop the other: those labels are still
        wanted, and the summary says exactly what to print again.
        """
        lines = [self._print_stock(stock, jobs) for stock, jobs
                 in sorted(plan.by_stock.items(), key=lambda kv: kv[0][1])]

        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "\n\n".join(lines), title="Order Labels"))
        self.ui.layout["footer"].update(Panel(
            "Press [cyan]Enter[/cyan] to go back", title=""))
        self.ui.render()
        self.ui.wait_back()

    @staticmethod
    def _print_stock(stock, jobs) -> str:
        """Print one printer's jobs; returns a line saying what happened."""
        from greenlight.hardware.interfaces import PrintJob, hardware_manager

        name = _roll_name(stock)
        total = sum(job.quantity for job in jobs)
        printer = hardware_manager.get_label_printer(stock)

        if not printer:
            return (f"[bold red]{name} printer: not configured.[/bold red] "
                    f"{total} label(s) not sent.")
        if not printer.is_ready():
            return (f"[bold red]{name} printer: not responding at "
                    f"{printer.ip_address}.[/bold red] {total} label(s) not "
                    f"sent. Check it is on and on the network.")

        sent = 0
        for job in jobs:
            data = dict(job.data)
            data["label_width_mm"], data["label_height_mm"] = stock
            if not printer.print_labels(PrintJob(template=job.template,
                                                 data=data,
                                                 quantity=job.quantity)):
                return (f"[bold red]{name} printer: failed on {job.quantity} x "
                        f"{job.sku} {job.label_name}.[/bold red] {sent} of "
                        f"{total} label(s) sent before the failure.")
            sent += job.quantity
        return f"[bold green]{name} printer: sent {sent} label(s).[/bold green]"
