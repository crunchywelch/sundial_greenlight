"""
Order Label Printing

Prints the retail labels for an order: the UPC label for the box back, the
side label for the spine, and the Prop 65 warning.

Reached from the fulfillment list (`f`, FulfillOrdersScreen), which carries
both unfulfilled Orders and unpaid wholesale drafts. Wholesale orders are
Shopify DRAFT orders until paid -- shopify_app/app/b2b.server.js creates a
draft and emails an invoice, and never completes it -- and their boxes get
labelled while they are still drafts, so the list has to show both.

Registration labels are NOT printed here. Those carry a unique code per
physical cable, keyed to serial numbers that live in Postgres rather than in
the order, so they stay in WholesaleBatchScreen where the serials are.

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


def draft_lifecycle(order) -> str:
    """Where a draft has got to, in words an operator can act on.

    The lifecycle trips people up: a draft becomes an Order only when it is
    completed -- the buyer paying the invoice, or someone completing it in
    admin -- and only Orders can be fulfilled. So an unpaid wholesale order
    can only have its labels printed, which looks like a bug unless the
    screen says why.
    """
    became = order.get("order")
    if became:
        status = (became.get("displayFulfillmentStatus") or "").replace("_", " ")
        return f"{became.get('name', 'order')} · {status.title() or 'order'}"
    status = (order.get("status") or "").replace("_", " ").title()
    return f"{status} · not an order yet" if status else "not an order yet"


class OrderLabelPrintScreen(Screen):
    """Choose which labels to print for one order, then print them by stock.

    Which labels is asked rather than fixed: not every retailer takes the UPC
    label, and the Prop 65 warning is only wanted on retail-boxed goods. The
    plan is re-costed on every toggle so the operator can see what a choice
    does -- dropping the UPC label takes a mixed run from one roll swap to
    none, which is the difference between two passes and one.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        order = self.context.get("label_order") or {}
        selected = {t: True for t in RETAIL_TEMPLATES}
        upcs = None          # fetched lazily, and only if a UPC label is on

        while True:
            if any(selected[t] for t in RETAIL_TEMPLATES
                   if TEMPLATE_LABELS[t][2]) and upcs is None:
                upcs = self._load_upcs(operator)

            templates = [t for t in RETAIL_TEMPLATES if selected[t]]
            plan = plan_order(order.get("line_items"), templates=templates,
                              upc_by_sku=upcs or {})

            self._render(operator, order, selected, plan)

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

    def _render(self, operator, order, selected, plan):
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

        swaps = plan.roll_swaps
        summary = (f"{plan.label_count} label(s) in {len(plan.jobs)} job(s), "
                   f"[bold]{swaps} roll swap{'s' if swaps != 1 else ''}[/bold]")

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
        """SKU -> UPC in one bulk call. Shopify's barcode field is the source
        of truth for retail UPCs."""
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
            return {}
        return {sku: v.get("barcode")
                for sku, v in rows.items() if v.get("barcode")}

    # -- printing -------------------------------------------------------

    def _print(self, operator, plan):
        """One pass per stock, pausing for the roll swap between them."""
        from greenlight.hardware.interfaces import PrintJob, hardware_manager

        printer = hardware_manager.get_label_printer()
        if not printer or not printer.is_ready():
            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "[bold red]No label printer available[/bold red]\n\n"
                "The TSC printer did not respond at startup.\n"
                "Check it is powered on and on the network.",
                title="Order Labels", style="red"))
            self.ui.layout["footer"].update(Panel(
                "Press [cyan]Enter[/cyan] to go back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return

        groups = sorted(plan.by_stock.items(), key=lambda kv: -kv[0][1])
        printed = 0
        for stock, jobs in groups:
            w, h = stock
            inches = f'{w / 25.4:.0f}" x {h / 25.4:.0f}"'
            total = sum(j.quantity for j in jobs)

            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"[bold]Load {inches} stock[/bold]\n\n"
                f"{total} label(s) in {len(jobs)} job(s) to print on it.\n\n"
                f"[dim]The TE210 has one media path, so each stock is its own\n"
                f"pass. Calibrate after swapping the roll.[/dim]",
                title=f"Order Labels — {inches}"))
            self.ui.layout["footer"].update(Panel(
                "[cyan]Enter[/cyan] = print this stock | "
                "[cyan]'s'[/cyan] = skip it | [cyan]'q'[/cyan] = stop",
                title="", border_style="green"))
            self.ui.render()

            try:
                answer = self.ui.console.input("Ready: ").strip().lower()
            except KeyboardInterrupt:
                break
            if answer == "q":
                break
            if answer == "s":
                continue

            failed = None
            for job in jobs:
                data = dict(job.data)
                data["label_width_mm"], data["label_height_mm"] = stock
                if printer.print_labels(PrintJob(template=job.template,
                                                 data=data,
                                                 quantity=job.quantity)):
                    printed += job.quantity
                else:
                    failed = job
                    break

            if failed:
                self.ui.layout["body"].update(Panel(
                    f"[bold red]Printing failed[/bold red]\n\n"
                    f"Stopped on {failed.quantity} x {failed.sku} "
                    f"{failed.label_name}.\n\n"
                    f"{printed} label(s) sent before the failure.",
                    title="Order Labels", style="red"))
                self.ui.layout["footer"].update(Panel(
                    "Press [cyan]Enter[/cyan] to go back", title=""))
                self.ui.render()
                self.ui.wait_back()
                return

        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold green]Sent {printed} label(s)[/bold green]",
            title="Order Labels"))
        self.ui.layout["footer"].update(Panel(
            "Press [cyan]Enter[/cyan] to go back", title=""))
        self.ui.render()
        self.ui.wait_back()
