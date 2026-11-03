"""Order fulfillment screens: Customer lookup, order processing, and cable assignment"""
import time
import logging

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.screens.cable import CableScreenBase
from greenlight import shopify_client
from greenlight import db

logger = logging.getLogger(__name__)

# How long to display a transient error before auto-returning to the scan loop.
# Blocking on console.input() here would freeze the scanner queue (MQTT scans
# get dropped by the next clear_queue), so we use a brief sleep instead.
ERROR_DISPLAY_SEC = 1.5

# How many fulfilled or cancelled orders the completed list fetches, newest first.
COMPLETED_LIMIT = 100


def _assign_pop_target(context):
    """Resolve the screen the cable-assignment flow should pop back to.

    Assignment is usually started from the cable scan screen, so that's the
    default. Callers that start it from elsewhere (e.g. the LTD inventory
    listing) put their own screen class in context['assign_return_to'] so the
    flow returns there instead of unwinding the whole stack.
    """
    target = context.get("assign_return_to")
    if target is not None:
        return target
    from greenlight.screens.cable import ScanCableLookupScreen
    return ScanCableLookupScreen


def order_line_items(order):
    """Flatten an order's lineItems to the shape the fulfillment flow wants.

    Lines with no SKU are dropped: they are shipping, discounts and the like,
    which no cable gets scanned against.
    """
    items = []
    for edge in (order.get("lineItems") or {}).get("edges") or []:
        node = edge.get("node") or {}
        sku = node.get("sku") or (node.get("variant") or {}).get("sku")
        if sku:
            items.append({
                "sku": sku,
                "title": node.get("title") or "Unknown",
                "quantity": node.get("quantity") or 0,
            })
    return items


def outstanding_orders(orders, drafts):
    """Merge unfulfilled Orders and still-open drafts into one list, newest first.

    Two kinds of work come through here. A website order needs its cables
    scanned against it with the SKU check, nothing more. A wholesale order
    also needs them assigned to the dealer, a registration label per cable,
    and box labels -- and it gets packed whether or not the invoice has been
    paid, so it may still be a draft. `channel` says which; it comes from the
    buyer (a company or not), not from draft-ness, since a paid wholesale
    order is still wholesale.

    Completed drafts are left out: completing one creates an Order, which is
    already in `orders` if it still needs fulfilling. They still matter, as
    the map from draft to Order -- see `completed_drafts()`.

    Each entry: {kind ("order"|"draft"), channel ("retail"|"wholesale"),
    id, name, customer, buyer, created, status, cancelled, line_items}.
    """
    from greenlight.screens.order_labels import draft_lifecycle

    # A completed draft's buyer, keyed by the Order it became, in case the
    # Order itself comes back without one.
    draft_buyers = {}
    for draft in drafts or []:
        became = (draft.get("order") or {}).get("id")
        buyer = shopify_client.wholesale_buyer(draft)
        if became and buyer:
            draft_buyers[became] = buyer

    def entry(kind, source, status, line_items):
        buyer = (shopify_client.wholesale_buyer(source)
                 or draft_buyers.get(source.get("id")))
        return {
            "kind": kind,
            "channel": "wholesale" if buyer else "retail",
            "id": source.get("id") or "",
            "name": source.get("name") or "?",
            "customer": source.get("customer") or {},
            "buyer": buyer,
            "created": source.get("createdAt") or "",
            "status": status,
            "cancelled": bool(source.get("cancelledAt")),
            "line_items": line_items,
        }

    merged = []
    for order in orders or []:
        status = ("Cancelled" if order.get("cancelledAt")
                  else (order.get("displayFulfillmentStatus") or "")
                  .replace("_", " ").title())
        merged.append(entry("order", order, status,
                            order_line_items(order)))
    for draft in drafts or []:
        if (draft.get("status") or "").upper() == "COMPLETED":
            continue
        merged.append(entry("draft", draft, draft_lifecycle(draft),
                            [li for li in draft.get("line_items") or []
                             if li.get("sku")]))
    merged.sort(key=lambda e: e["created"], reverse=True)
    return merged


def completed_orders(orders, drafts):
    """Fulfilled and cancelled Orders as list entries, newest first.

    Same shape as outstanding_orders(). Open drafts are left out, since a
    draft isn't an order yet, let alone a finished one; `drafts` is still
    needed to find the buyer of an Order that came from one.
    """
    return [e for e in outstanding_orders(orders, drafts)
            if e["kind"] == "order"]


def completed_drafts(drafts):
    """{draft GID: Order GID} for drafts that have become Orders."""
    return {d["id"]: d["order"]["id"] for d in drafts or []
            if d.get("id") and (d.get("order") or {}).get("id")}


def fulfillment_context(context, entry):
    """Context for OrderFulfillScanScreen from one outstanding_orders() entry.

    `company_gid` is what makes a scan wholesale: the cable is recorded
    against the dealer with shopify_gid left NULL, so its end buyer can still
    register it, and a registration label prints as each cable is scanned.
    """
    context = context.copy()
    buyer = entry.get("buyer") or {}
    context["selected_customer"] = entry.get("customer") or {}
    context["company_gid"] = buyer.get("company_gid")
    context["location_gid"] = buyer.get("location_gid")
    context["dealer_name"] = buyer.get("display")
    context["order_id"] = entry["id"]
    context["order_name"] = entry["name"]
    context["line_items"] = entry["line_items"]
    context["cancelled"] = entry.get("cancelled", False)
    context["scanned_cables"] = []
    return context


def _one_line(text):
    """A table cell that shortens to fit, so each row stays one line for paging."""
    return Text(text, no_wrap=True, overflow="ellipsis")


class OrdersScreen(Screen):
    """Every order: open ones to pack, and completed ones to look back at.

    This is what `o` lands on, showing open orders: website orders and
    wholesale orders, paid or still drafts. Picking one goes to the scan
    screen, which behaves per channel. `c` switches to completed orders
    (fulfilled or cancelled), which open view-only so a shipped order can't pick up a cable by accident.

    Shopify's status decides the list, because Greenlight never marks anything
    fulfilled. A fully scanned order stays open until it ships, and its Cables
    column is what says it's packed.
    """

    view = "open"       # or "completed"; survives returning from an order
    page = 0

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        entries = self._load(operator)

        while True:
            page_size = self.ui.page_size(minimum=4)
            total = len(entries or [])
            pages = max(1, (total + page_size - 1) // page_size)
            self.page = min(self.page, pages - 1)

            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(self._body(entries, page_size))
            self.ui.layout["footer"].update(Panel(
                " | ".join(self._hints(total, pages)),
                title="Orders", border_style="green"))
            self.ui.render()

            try:
                choice = self.ui.console.input("Choose: ").strip().lower()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.POP)

            if choice in ("", "q"):
                if self.view == "open":
                    return ScreenResult(NavigationAction.POP)
                entries = self._switch_view(operator)
            elif choice == "c":
                entries = self._switch_view(operator)
            elif choice == "l":
                return ScreenResult(NavigationAction.PUSH,
                                    CustomerLookupScreen, self.context)
            elif choice == "n" and self.page < pages - 1:
                self.page += 1
            elif choice == "p" and self.page > 0:
                self.page -= 1
            elif entries and choice.isdigit() and 1 <= int(choice) <= total:
                result = self._open_order(entries[int(choice) - 1])
                if result:
                    return result

    def _switch_view(self, operator):
        self.view = "completed" if self.view == "open" else "open"
        self.page = 0
        return self._load(operator)

    def _load(self, operator):
        """This view's entries, or None if Shopify couldn't be read."""
        completed = self.view == "completed"
        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[yellow]Loading {self.view} orders from Shopify...[/yellow]",
            title="Orders"))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()

        try:
            orders = (shopify_client.get_completed_orders(limit=COMPLETED_LIMIT)
                      if completed
                      else shopify_client.get_unfulfilled_orders(limit=50))
            drafts = shopify_client.get_draft_orders(limit=50)
            moved = db.relink_order_cables(completed_drafts(drafts))
            if moved:
                logger.info("Moved %d cable(s) from paid drafts to their orders",
                            moved)
            entries = (completed_orders(orders, drafts) if completed
                       else outstanding_orders(orders, drafts))
        except Exception as e:
            logger.error("Failed to load %s orders: %s", self.view, e)
            return None

        self.cables_by_order = db.get_cables_for_orders(
            [e["id"] for e in entries])
        return entries

    def _body(self, entries, page_size):
        completed = self.view == "completed"
        if entries is None:
            return Panel(
                "[bold red]Can't reach Shopify[/bold red]\n\n"
                "Orders could not be loaded. This is a connection or\n"
                "credentials issue.\n\n"
                "[dim]Customer lookup needs Shopify too, but try it if\n"
                "you have a name.[/dim]",
                title="Orders", style="red")
        if not entries:
            message = ("[dim]No completed orders.[/dim]" if completed else
                       "[green]Nothing open.[/green]\n\n"
                       "[dim]No unfulfilled orders and no open wholesale\n"
                       "drafts.[/dim]")
            return Panel(message, title="Orders")

        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="green", width=3)
        table.add_column("Order", style="white", width=7)
        table.add_column("Type", width=9)
        table.add_column("For", max_width=24)
        table.add_column("Cables", justify="right", width=7)
        table.add_column("Status", style="dim", max_width=30)
        first = self.page * page_size
        for i, e in enumerate(entries[first:first + page_size], first + 1):
            if e["buyer"]:
                who = e["buyer"]["display"]
                kind = "[magenta]Wholesale[/magenta]"
            else:
                who = e["customer"].get("displayName") or "—"
                kind = "Website"
            cables = self.cables_by_order
            table.add_row(str(i), e["name"], kind, _one_line(who),
                          cables_cell(e["line_items"],
                                      None if cables is None
                                      else cables.get(e["id"], []),
                                      closed=completed),
                          _one_line(e["status"]))

        if completed:
            subtitle = "View only: nothing gets assigned from here"
            if len(entries) >= COMPLETED_LIMIT:
                subtitle = f"Newest {COMPLETED_LIMIT}. " + subtitle
        else:
            subtitle = ("Wholesale: registration label per cable, "
                        "then box labels")
        return Panel(table, subtitle=subtitle,
                     title="Completed Orders" if completed else "Open Orders")

    def _hints(self, total, pages):
        hints = []
        if total:
            hints.append(f"Enter [cyan]1-{total}[/cyan] to open")
        if pages > 1:
            hints.append(f"Page {self.page + 1}/{pages}")
            if self.page < pages - 1:
                hints.append("[cyan]'n'[/cyan] = Next")
            if self.page > 0:
                hints.append("[cyan]'p'[/cyan] = Prev")
        hints.append("[cyan]'c'[/cyan] = Open orders"
                     if self.view == "completed"
                     else "[cyan]'c'[/cyan] = Completed orders")
        hints.append("[cyan]'l'[/cyan] = Lookup customer")
        hints.append("[cyan]'q'[/cyan] = Back")
        return hints

    def _open_order(self, entry):
        if not entry["line_items"]:
            self.ui.layout["body"].update(Panel(
                "[red]No cable items (with SKUs) in this order[/red]",
                title="Orders"))
            self.ui.layout["footer"].update(Panel(
                "Press [cyan]Enter[/cyan] to go back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return None
        context = fulfillment_context(self.context, entry)
        if self.view == "completed":
            return ScreenResult(NavigationAction.PUSH, CompletedOrderScreen,
                                context)
        # Back from the scan screen means this list, not the scan hub.
        context["assign_return_to"] = OrdersScreen
        return ScreenResult(NavigationAction.PUSH, OrderFulfillScanScreen,
                            context)


class CustomerLookupScreen(Screen):
    """Search for customers by name"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "Search for customers by name to view their orders and information",
            title="Customer Lookup"
        ))
        self.ui.layout["footer"].update(Panel(
            "[cyan]Enter customer name (or 'q' to go back)[/cyan]",
            title="Search"
        ))
        self.ui.render()

        try:
            search_name = self.ui.console.input("Customer name: ").strip()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if search_name.lower() == 'q':
            return ScreenResult(NavigationAction.POP)

        if not search_name:
            # Empty search - re-display screen
            return ScreenResult(NavigationAction.REPLACE, CustomerLookupScreen, self.context)

        # Search for customers
        self.ui.layout["body"].update(Panel(
            f"[yellow]Searching for '{search_name}'...[/yellow]",
            title="Customer Lookup"
        ))
        self.ui.render()

        try:
            customers = shopify_client.search_customers_by_name(search_name)
        except Exception as e:
            logger.error("Customer search failed: %s", e)
            show_shopify_down(self.ui, "Customer Lookup", "Customers")
            return ScreenResult(NavigationAction.REPLACE, CustomerLookupScreen, self.context)

        if not customers:
            self.ui.layout["body"].update(Panel(
                f"[red]No customers found matching '{search_name}'[/red]\n\n[dim]Press enter to search again[/dim]",
                title="Customer Lookup"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, CustomerLookupScreen, self.context)

        # Display search results
        new_context = self.context.copy()
        new_context["customers"] = customers
        new_context["search_name"] = search_name
        return ScreenResult(NavigationAction.PUSH, CustomerSearchResultsScreen, new_context)


def show_shopify_down(ui, title, what):
    """Say Shopify couldn't be read, and wait for the operator to go back.

    Never show this kind of failure as an empty result: "no orders" is an
    answer an operator acts on.
    """
    ui.layout["body"].update(Panel(
        f"[bold red]Can't reach Shopify[/bold red]\n\n"
        f"{what} could not be loaded. This is a connection or\n"
        f"credentials issue, not a missing record.",
        title=title, style="red"))
    ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
    ui.render()
    ui.wait_back()


class CustomerSearchResultsScreen(Screen):
    """Display customer search results and allow selection"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customers = self.context.get("customers", [])
        search_name = self.context.get("search_name", "")
        fulfillment_mode = self.context.get("fulfillment_mode", False)

        # Create results table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="green", width=3)
        table.add_column("Name", style="white")
        table.add_column("Band", style="magenta")
        table.add_column("Email", style="dim")
        table.add_column("Orders", justify="right", style="yellow")
        table.add_column("Total Spent", justify="right", style="green")

        for i, customer in enumerate(customers, 1):
            name = customer.get("displayName") or ""
            band = shopify_client.get_band_company(customer) or ""
            email = customer.get("email") or ""

            num_orders_raw = customer.get("numberOfOrders") or 0
            num_orders = str(num_orders_raw) if int(num_orders_raw) else ""

            amount_spent = customer.get("amountSpent") or {}
            amount = float(amount_spent.get("amount") or 0)
            spent = f"${amount:.2f}" if amount else ""

            table.add_row(str(i), name, band, email, num_orders, spent)

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            table,
            title=f"Search Results for '{search_name}' ({len(customers)} found)"
        ))

        if len(customers) == 1:
            footer_text = "[cyan]Press Enter to select, 'n' for new search, or 'q' to go back[/cyan]"
        else:
            footer_text = "[cyan]Enter number to view details, 'n' for new search, or 'q' to go back[/cyan]"
        self.ui.layout["footer"].update(Panel(footer_text, title="Select Customer"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

        # Auto-select if only one result and user pressed Enter
        if choice == '' and len(customers) == 1:
            choice = '1'

        if choice == 'q':
            return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))
        elif choice == 'n':
            return ScreenResult(NavigationAction.REPLACE, CustomerLookupScreen, self.context)
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(customers):
                new_context = self.context.copy()
                new_context["selected_customer"] = customers[idx]
                # Preserve cable assignment context if it exists
                if "assign_cable_serial" in self.context:
                    new_context["assign_cable_serial"] = self.context["assign_cable_serial"]
                    new_context["assign_cable_sku"] = self.context.get("assign_cable_sku")

                # In fulfillment mode, go straight to order selection
                if fulfillment_mode:
                    return ScreenResult(NavigationAction.PUSH, OrderSelectionScreen, new_context)

                return ScreenResult(NavigationAction.PUSH, CustomerDetailScreen, new_context)

        # Invalid choice - re-display
        return ScreenResult(NavigationAction.REPLACE, CustomerSearchResultsScreen, self.context)


class CustomerDetailScreen(Screen):
    """Display detailed customer information and recent orders"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})

        # Check if we're in cable assignment mode (coming from cable scan screen)
        assign_cable_serial = self.context.get("assign_cable_serial")
        if assign_cable_serial:
            return self.assign_cable_and_return(operator, customer, assign_cable_serial)

        # Build customer info display
        name = customer.get("displayName") or "(no name)"
        band_company = shopify_client.get_band_company(customer)
        email = customer.get("email")

        # Try to get phone from customer level, then from address
        address = customer.get("defaultAddress")
        phone = customer.get("phone") or (address.get("phone") if address else None)

        # Convert numberOfOrders to int (Shopify returns it as string)
        num_orders = int(customer.get("numberOfOrders") or 0)

        amount_spent = customer.get("amountSpent") or {}
        amount = float(amount_spent.get("amount") or 0)
        spent = (
            f"${amount:.2f} {amount_spent.get('currencyCode', 'USD')}"
            if amount else None
        )

        # Show just city, state — full address isn't needed and country-only is noise
        location = ""
        if address:
            location = ", ".join(
                p for p in (address.get("city"), address.get("province")) if p
            )

        # Fetch most recent order and assigned cables
        customer_id = customer.get("id", "")
        recent_orders_failed = False
        try:
            recent_orders = shopify_client.get_customer_orders(customer_id, limit=1)
        except Exception as e:
            logger.error("Failed to load last order for %s: %s", customer_id, e)
            recent_orders = []
            recent_orders_failed = True
        assigned_cables = db.get_cables_for_customer(customer_id)

        # Build sections, skipping empty ones
        sections = []

        contact_lines = [f"[bold cyan]Name:[/bold cyan] {name}"]
        if band_company:
            contact_lines.append(f"[bold cyan]Band:[/bold cyan] {band_company}")
        if email:
            contact_lines.append(f"[bold cyan]Email:[/bold cyan] {email}")
        if phone:
            contact_lines.append(f"[bold cyan]Phone:[/bold cyan] {phone}")
        if location:
            contact_lines.append(f"[bold cyan]Location:[/bold cyan] {location}")
        sections.append("\n".join(contact_lines))

        if num_orders > 0:
            order_lines = [f"[bold yellow]Order Count:[/bold yellow] {num_orders}"]
            if spent:
                order_lines.append(f"[bold yellow]Total Spent:[/bold yellow] {spent}")
            sections.append("\n".join(order_lines))

        if recent_orders_failed:
            sections.append("[bold red]Can't reach Shopify:[/bold red] "
                            "last order not loaded")

        if recent_orders:
            order = recent_orders[0]
            order_name = order.get("name") or "N/A"
            order_date = (order.get("createdAt") or "")[:10]
            order_status = order.get("displayFulfillmentStatus") or "N/A"
            order_financial = order.get("displayFinancialStatus") or "N/A"

            total_price = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
            order_total = f"${float(total_price.get('amount') or 0):.2f}"

            line_items = (order.get("lineItems") or {}).get("edges") or []
            items_summary = []
            for item_edge in line_items[:3]:
                item = item_edge.get("node") or {}
                title = item.get("title") or "Unknown"
                qty = item.get("quantity") or 0
                items_summary.append(f"  • {title} (x{qty})")
            if len(line_items) > 3:
                items_summary.append(f"  • ... and {len(line_items) - 3} more items")

            last_order = (
                f"[bold magenta]Last Order:[/bold magenta] {order_name} - {order_date}\n"
                f"[bold magenta]Status:[/bold magenta] {order_status} / {order_financial}\n"
                f"[bold magenta]Total:[/bold magenta] {order_total}"
            )
            if items_summary:
                last_order += "\n[bold magenta]Items:[/bold magenta]\n" + "\n".join(items_summary)
            sections.append(last_order)
        elif num_orders > 0:
            sections.append(
                f"[dim]Customer has {num_orders} order(s) but they are not accessible via API[/dim]"
            )

        # Assigned cables — always show the count
        cables_text = f"[bold magenta]Assigned Cables:[/bold magenta] {len(assigned_cables)}"
        for cable in assigned_cables[:5]:
            kind = cable.get('kind')
            if kind in ('misc', 'ltd') and cable.get('description'):
                cable_desc = f"{cable['series']} {cable['length']}ft - {cable['description']}"
            else:
                cable_desc = f"{cable['series']} {cable['length']}ft {cable.get('pattern_name') or ''}"
            cables_text += f"\n  • {cable['serial_number']} - {cable_desc.rstrip()}"
        if len(assigned_cables) > 5:
            cables_text += f"\n  • ... and {len(assigned_cables) - 5} more"
        sections.append(cables_text)

        customer_info = "\n\n".join(sections)

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(customer_info, title="Customer Details"))

        footer_parts = [
            "[cyan]'o'[/cyan] = orders",
            "[cyan]'a'[/cyan] = assign cables",
        ]
        if assigned_cables:
            footer_parts.append("[cyan]'u'[/cyan] = unassign cable")
            footer_parts.append("[cyan]'p'[/cyan] = print all labels")
        footer_parts.extend([
            "[cyan]'f'[/cyan] = fulfill order",
            "[cyan]'q'[/cyan] = back",
        ])
        footer_text = " | ".join(footer_parts)
        self.ui.layout["footer"].update(Panel(footer_text, title=""))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice == 'o':
            return ScreenResult(NavigationAction.PUSH, CustomerOrdersScreen, self.context)
        elif choice == 'a':
            # Check for unfulfilled orders before allowing direct assignment
            # This check exists to stop cables going on around an open order,
            # so not knowing isn't the same as there being none.
            try:
                orders = shopify_client.get_customer_orders(customer_id, limit=25)
            except Exception as e:
                logger.error("Failed to check open orders for %s: %s", customer_id, e)
                show_shopify_down(self.ui, "Assign Cables",
                                  "This customer's open orders")
                return ScreenResult(NavigationAction.REPLACE, CustomerDetailScreen, self.context)
            unfulfilled = [
                o for o in orders
                if (o.get("displayFulfillmentStatus") or "").upper()
                in ("UNFULFILLED", "PARTIALLY_FULFILLED", "")
            ]
            if unfulfilled:
                try:
                    confirm = self.ui.console.input(
                        "This customer has open orders. Fulfill them instead? (y/n): "
                    ).strip().lower()
                except KeyboardInterrupt:
                    confirm = 'n'
                if confirm == 'y':
                    return ScreenResult(NavigationAction.PUSH, OrderSelectionScreen, self.context)
            return ScreenResult(NavigationAction.PUSH, AssignCablesScreen, self.context)
        elif choice == 'u' and assigned_cables:
            new_context = self.context.copy()
            new_context["assigned_cables"] = assigned_cables
            return ScreenResult(NavigationAction.PUSH, UnassignCableScreen, new_context)
        elif choice == 'p' and assigned_cables:
            return ScreenResult(NavigationAction.PUSH, PrintCustomerLabelsScreen, self.context)
        elif choice == 'f':
            return ScreenResult(NavigationAction.PUSH, OrderSelectionScreen, self.context)
        elif choice in ('', 'q'):
            return ScreenResult(NavigationAction.POP)

        # Invalid choice - re-display
        return ScreenResult(NavigationAction.REPLACE, CustomerDetailScreen, self.context)

    def assign_cable_and_return(self, operator, customer, cable_serial):
        """Assign a cable to customer and return to cable scan screen

        This is called when coming from the cable scan screen with a cable to assign
        """
        customer_name = customer.get("displayName", "Customer")
        customer_gid = customer.get("id", "")
        cable_sku = self.context.get("assign_cable_sku", "Unknown")

        # Show assignment in progress
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[yellow]Assigning cable {cable_serial} to {customer_name}...[/yellow]",
            title="Assign Cable to Customer"
        ))
        self.ui.layout["footer"].update(Panel("", title=""))
        self.ui.render()

        # Perform assignment
        result = db.assign_cable_to_customer(cable_serial, customer_gid)

        if result.get('success'):
            # Pop back to cable info screen (it will show the assignment)
            return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))
        else:
            # Error occurred
            error_type = result.get('error')
            error_msg = result.get('message')

            if error_type == 'already_assigned':
                # Cable is already assigned - ask if user wants to reassign
                existing_gid = result.get('existing_customer_gid', 'unknown')

                # Try to get existing customer name
                existing_customer_name = "another customer"
                try:
                    if existing_gid and existing_gid != 'unknown':
                        customer_numeric_id = existing_gid.split('/')[-1]
                        existing_customer = shopify_client.get_customer_by_id(customer_numeric_id)
                        if existing_customer:
                            existing_customer_name = existing_customer.get('displayName') or "another customer"
                except:
                    pass

                reassign_prompt = f"""[yellow]⚠️  Cable Already Assigned[/yellow]

Cable [bold]{cable_serial}[/bold] is currently assigned to:
[cyan]{existing_customer_name}[/cyan]

Do you want to reassign it to [bold green]{customer_name}[/bold green]?"""

                self.ui.layout["body"].update(Panel(reassign_prompt, title="Cable Already Assigned"))
                self.ui.layout["footer"].update(Panel(
                    "[green]y[/green] = Reassign | [cyan]n[/cyan] = Cancel | [yellow]q[/yellow] = Back to scanning",
                    title="Reassign?"
                ))
                self.ui.render()

                try:
                    choice = self.ui.console.input("").strip().lower()
                except KeyboardInterrupt:
                    return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

                if choice == 'y' or choice == 'yes':
                    # Force reassignment
                    self.ui.layout["body"].update(Panel(
                        f"[yellow]Reassigning cable {cable_serial}...[/yellow]",
                        title="Reassigning Cable"
                    ))
                    self.ui.render()

                    reassign_result = db.force_reassign_cable(cable_serial, customer_gid)

                    if reassign_result.get('success'):
                        return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))
                    else:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ Error reassigning cable: {reassign_result.get('message', 'Unknown error')}[/red]",
                            title="Error"
                        ))
                        self.ui.layout["footer"].update(Panel("", title=""))
                        self.ui.render()
                        time.sleep(ERROR_DISPLAY_SEC)

                        return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

                else:
                    # Cancel or go back to scanning
                    return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

            else:
                # Other error
                error_display = f"[red]❌ Assignment Error[/red]\n\n{error_msg}"

                self.ui.layout["body"].update(Panel(error_display, title="Assignment Failed"))
                self.ui.layout["footer"].update(Panel("", title=""))
                self.ui.render()
                time.sleep(ERROR_DISPLAY_SEC)

                # Pop back to cable scan screen
                return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))


class PrintCustomerLabelsScreen(CableScreenBase):
    """Print labels for every cable assigned to a customer."""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        customer_id = customer.get("id", "")
        customer_name = customer.get("displayName") or "Customer"

        cables = db.get_cables_for_customer(customer_id)

        self.ui.header(operator)

        if not cables:
            self.ui.layout["body"].update(
                Panel("No cables assigned to this customer.", title="Print Labels")
            )
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            try:
                self.ui.wait_back()
            except KeyboardInterrupt:
                pass
            return ScreenResult(NavigationAction.POP)

        from greenlight.hardware.interfaces import hardware_manager
        from greenlight.hardware.tsc_label_printer import CABLE_ROLL_MM
        if not hardware_manager.get_label_printer(CABLE_ROLL_MM):
            self.ui.layout["body"].update(
                Panel("No label printer available.", title="Print Labels")
            )
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            try:
                self.ui.wait_back()
            except KeyboardInterrupt:
                pass
            return ScreenResult(NavigationAction.POP)

        # Confirm before sending a batch of labels to the printer
        self.ui.layout["body"].update(Panel(
            f"Print labels for [bold]{len(cables)}[/bold] cable(s) "
            f"assigned to {customer_name}?",
            title="Print Labels",
        ))
        self.ui.layout["footer"].update(
            Panel("[green]Enter[/green] = print | [red]'q'[/red] = cancel", title="")
        )
        self.ui.render()
        try:
            confirm = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            confirm = 'q'
        if confirm == 'q':
            return ScreenResult(NavigationAction.POP)

        printed = 0
        failed = []
        for i, cable in enumerate(cables, 1):
            serial = cable.get('serial_number')
            self.ui.layout["body"].update(Panel(
                f"Printing label {i} of {len(cables)}: {serial}",
                title="Printing Labels",
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            if self.print_label_for_cable(operator, cable):
                printed += 1
            else:
                failed.append(serial)

        summary = f"[green]Printed {printed} of {len(cables)} label(s) for {customer_name}.[/green]"
        if failed:
            summary += "\n[red]Failed:[/red] " + ", ".join(failed)
        self.ui.layout["body"].update(Panel(summary, title="Print Labels"))
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()
        try:
            self.ui.wait_back()
        except KeyboardInterrupt:
            pass
        return ScreenResult(NavigationAction.POP)


class UnassignCableScreen(Screen):
    """Show customer's assigned cables and allow unassignment"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        assigned_cables = self.context.get("assigned_cables", [])
        customer_name = customer.get("displayName") or "Customer"

        if not assigned_cables:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "[dim]No cables assigned to this customer[/dim]",
                title="Unassign Cable"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Build cable list table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="green", width=3)
        table.add_column("Serial", style="white")
        table.add_column("Cable", style="dim")
        table.add_column("Tested", justify="center", style="yellow")

        for i, cable in enumerate(assigned_cables, 1):
            kind = cable.get('kind')
            if kind in ('misc', 'ltd') and cable.get('description'):
                cable_desc = f"{cable['series']} {cable['length']}ft - {cable['description']}"
            else:
                cable_desc = f"{cable['series']} {cable['length']}ft {cable.get('pattern_name') or ''}".rstrip()
            tested = "[green]Yes[/green]" if cable.get('test_passed') else "[dim]No[/dim]"
            table.add_row(str(i), cable['serial_number'], cable_desc, tested)

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            table,
            title=f"Cables Assigned to {customer_name}"
        ))
        self.ui.layout["footer"].update(Panel(
            "[cyan]Enter cable number to unassign, or 'q' to go back[/cyan]",
            title="Unassign Cable"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice == 'q' or not choice:
            return ScreenResult(NavigationAction.POP)

        if not choice.isdigit():
            return ScreenResult(NavigationAction.REPLACE, UnassignCableScreen, self.context)

        idx = int(choice) - 1
        if idx < 0 or idx >= len(assigned_cables):
            return ScreenResult(NavigationAction.REPLACE, UnassignCableScreen, self.context)

        cable = assigned_cables[idx]
        serial = cable['serial_number']

        # Confirm unassignment
        self.ui.layout["body"].update(Panel(
            f"Unassign [bold]{serial}[/bold] from [bold cyan]{customer_name}[/bold cyan]?\n\n"
            f"The cable will be returned to available inventory.",
            title="Confirm Unassign"
        ))
        self.ui.layout["footer"].update(Panel(
            "[green]y[/green] = Confirm | [cyan]Enter[/cyan] = Cancel",
            title=""
        ))
        self.ui.render()

        try:
            confirm = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if confirm not in ('y', 'yes'):
            return ScreenResult(NavigationAction.REPLACE, UnassignCableScreen, self.context)

        # Perform unassignment. This screen is reached from a customer's cable
        # list, so it always releases the end owner — never the dealer, whose
        # attribution must survive the customer being unassigned.
        result = db.unassign_cable(serial, channel='retail')

        if result.get('success'):
            # Cable is back in the available pool — push the higher count to Shopify.
            cable_record = db.get_audio_cable(serial)
            if cable_record:
                ok, err = shopify_client.sync_inventory_for_cable(cable_record)
                if not ok:
                    logger.warning("Shopify inventory sync failed for %s: %s", serial, err)
            self.ui.layout["body"].update(Panel(
                f"[green]Cable {serial} unassigned from {customer_name}[/green]",
                title="Unassigned"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"[red]Error: {result.get('message', 'Unknown error')}[/red]",
                title="Error"
            ))
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()
        self.ui.wait_back()

        # Refresh the assigned cables list and go back to customer detail
        return ScreenResult(NavigationAction.POP)


class CustomerOrdersScreen(Screen):
    """Display customer's recent orders"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        customer_id = customer.get("id", "")
        customer_name = customer.get("displayName", "Customer")

        # Fetch orders
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "[yellow]Loading orders...[/yellow]",
            title=f"Orders for {customer_name}"
        ))
        self.ui.render()

        try:
            orders = shopify_client.get_customer_orders(customer_id, limit=10)
        except Exception as e:
            logger.error("Failed to load orders for %s: %s", customer_id, e)
            show_shopify_down(self.ui, f"Orders for {customer_name}", "Orders")
            return ScreenResult(NavigationAction.POP)

        if not orders:
            self.ui.layout["body"].update(Panel(
                "[dim]No orders found for this customer[/dim]",
                title=f"Orders for {customer_name}"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Create orders table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("Order", style="white")
        table.add_column("Date", style="dim")
        table.add_column("Status", style="yellow")
        table.add_column("Total", justify="right", style="green")
        table.add_column("Items", justify="right", style="cyan")

        for order in orders:
            order_name = order.get("name") or "N/A"
            created_at = (order.get("createdAt") or "")[:10]  # Just the date part
            fulfillment_status = order.get("displayFulfillmentStatus") or "N/A"

            total_price = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
            total = f"${float(total_price.get('amount') or 0):.2f}" if total_price else "$0.00"

            line_items = (order.get("lineItems") or {}).get("edges") or []
            num_items = sum((item.get("node") or {}).get("quantity") or 0 for item in line_items)

            table.add_row(order_name, created_at, fulfillment_status, total, str(num_items))

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(table, title=f"Recent Orders for {customer_name}"))
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()

        self.ui.wait_back()
        return ScreenResult(NavigationAction.POP)


class OrderSelectionScreen(Screen):
    """Display unfulfilled orders for a customer and allow selection for fulfillment"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        customer_id = customer.get("id", "")
        customer_name = customer.get("displayName", "Customer")

        # Fetch orders
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[yellow]Loading orders for {customer_name}...[/yellow]",
            title="Order Selection"
        ))
        self.ui.render()

        try:
            orders = shopify_client.get_customer_orders(customer_id, limit=25)
        except Exception as e:
            logger.error("Failed to load orders for %s: %s", customer_id, e)
            show_shopify_down(self.ui, "Order Selection", "Orders")
            return ScreenResult(NavigationAction.POP)

        # Filter to unfulfilled/partially fulfilled orders
        unfulfilled_orders = []
        for order in orders:
            status = (order.get("displayFulfillmentStatus") or "").upper()
            if status in ("UNFULFILLED", "PARTIALLY_FULFILLED", ""):
                unfulfilled_orders.append(order)

        if not unfulfilled_orders:
            self.ui.layout["body"].update(Panel(
                f"[dim]No unfulfilled orders found for {customer_name}[/dim]",
                title="Order Selection"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        # Single order - skip selection and go directly to fulfillment
        if len(unfulfilled_orders) == 1:
            return self._select_order(unfulfilled_orders[0])

        # Create orders table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="green", width=3)
        table.add_column("Order", style="white")
        table.add_column("Date", style="dim")
        table.add_column("Status", style="yellow")
        table.add_column("Total", justify="right", style="green")
        table.add_column("Items", justify="right", style="cyan")

        for i, order in enumerate(unfulfilled_orders, 1):
            order_name = order.get("name") or "N/A"
            created_at = (order.get("createdAt") or "")[:10]
            fulfillment_status = order.get("displayFulfillmentStatus") or "UNFULFILLED"

            total_price = (order.get("totalPriceSet") or {}).get("shopMoney") or {}
            total = f"${float(total_price.get('amount') or 0):.2f}" if total_price else "$0.00"

            line_items = (order.get("lineItems") or {}).get("edges") or []
            num_items = sum((item.get("node") or {}).get("quantity") or 0 for item in line_items)

            table.add_row(str(i), order_name, created_at, fulfillment_status, total, str(num_items))

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            table,
            title=f"Unfulfilled Orders for {customer_name} ({len(unfulfilled_orders)} found)"
        ))

        footer_text = "[cyan]Enter number to fulfill, or 'q' to go back[/cyan]"
        self.ui.layout["footer"].update(Panel(footer_text, title="Select Order"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice == 'q':
            return ScreenResult(NavigationAction.POP)
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(unfulfilled_orders):
                return self._select_order(unfulfilled_orders[idx])

        # Invalid choice - re-display
        return ScreenResult(NavigationAction.REPLACE, OrderSelectionScreen, self.context)


    def _select_order(self, selected_order):
        """Prepare context for a selected order and navigate to fulfillment scan"""
        (entry,) = outstanding_orders([selected_order], [])
        if not entry["line_items"]:
            self.ui.layout["body"].update(Panel(
                "[red]No cable items (with SKUs) found in this order[/red]",
                title="Order Selection"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.REPLACE, OrderSelectionScreen, self.context)

        # The customer-first route already chose the customer; keep it.
        new_context = fulfillment_context(self.context, entry)
        new_context["selected_customer"] = self.context.get("selected_customer", {})
        return ScreenResult(NavigationAction.PUSH, OrderFulfillScanScreen, new_context)


def match_cables_to_lines(line_items, cables):
    """Which cables' serials count toward each line item, in line order.

    Each cable counts once. An order can list the same SKU on two lines, and
    giving both lines the same cables would report the order complete with
    half of them missing. Cables beyond what a SKU's lines need land on its
    last line, so an over-scan shows as 2/1 rather than vanishing.
    """
    by_sku = {}
    for cable in cables:
        by_sku.setdefault(cable['variant_sku'], []).append(cable['serial_number'])
    for serials in by_sku.values():
        serials.sort()

    last_line = {item['sku']: i for i, item in enumerate(line_items)}
    matched = []
    for i, item in enumerate(line_items):
        remaining = by_sku.get(item['sku'], [])
        take = len(remaining) if i == last_line[item['sku']] else item['quantity']
        matched.append(remaining[:take])
        by_sku[item['sku']] = remaining[take:]
    return matched


def line_quantities(line_items):
    """{SKU: quantity ordered}, adding up a SKU that's on more than one line."""
    quantities = {}
    for item in line_items:
        quantities[item["sku"]] = quantities.get(item["sku"], 0) + item["quantity"]
    return quantities


def pick_cable(choice, cables):
    """The cable an operator chose, by its row number or by scanning its serial.

    A scanned serial is zero-padded, so 000002 is a cable and never row 2.
    """
    choice = choice.strip()
    if choice.isdigit() and choice == str(int(choice)) and 1 <= int(choice) <= len(cables):
        return cables[int(choice) - 1]
    from greenlight.db import format_serial_number
    if choice.isdigit():
        choice = format_serial_number(choice)
    return next((c for c in cables if c["serial_number"] == choice), None)


def cables_cell(line_items, cables, closed=False):
    """An order list's Cables column: `2/3` scanned of needed.

    `cables` is None when the database couldn't be read, which shows as `?/3`
    rather than a false `0/3`. On an open order the colour says what's left to
    pack, and only cables matching a line count. A closed order counts every
    cable recorded on it, since a one-off can ship under a different SKU from
    its line, and 0/3 there only means no record, so it isn't flagged.
    """
    needed = sum(item["quantity"] for item in line_items)
    if cables is None:
        return f"[dim]?/{needed}[/dim]"
    scanned = (len(cables) if closed else
               sum(len(s) for s in match_cables_to_lines(line_items, cables)))
    text = f"{scanned}/{needed}"
    if scanned >= needed and needed:
        return f"[green]{text}[/green]"
    if closed:
        return f"[dim]{text}[/dim]"
    return f"[yellow]{text}[/yellow]" if scanned else text


def other_cables(line_items, cables):
    """Cables recorded on an order whose SKU isn't on any of its lines."""
    skus = {item["sku"] for item in line_items}
    return [c for c in cables if c["variant_sku"] not in skus]


def order_progress_table(line_items, cables, closed=False):
    """Each line's serials and count. Returns (table, every line is scanned).

    On a closed order a shortfall isn't work still to do, so it reads
    "not scanned" rather than "remaining", or "no SKU match" if the order has
    other cables that could be the ones that shipped.
    """
    closed_status = ("no SKU match" if other_cables(line_items, cables)
                     else "not scanned")
    table = Table(show_header=True, header_style="bold cyan", expand=True)
    table.add_column("SKU", style="white")
    table.add_column("Title", style="dim")
    table.add_column("Cable")
    table.add_column("Progress", justify="center", style="yellow")
    table.add_column("Status", justify="center")

    all_complete = True
    for item, serials in zip(line_items, match_cables_to_lines(line_items, cables)):
        needed = item['quantity']
        scanned = len(serials)
        if scanned >= needed:
            status = "[bold green]DONE[/bold green]"
        else:
            all_complete = False
            status = (f"[dim]{needed - scanned} {closed_status}[/dim]" if closed
                      else f"[yellow]{needed - scanned} remaining[/yellow]")
        table.add_row(item['sku'], item['title'],
                      ", ".join(serials) or "[dim]—[/dim]",
                      f"{scanned}/{needed}", status)
    return table, all_complete


def box_label_context(context, order_name, buyer_name, line_items):
    """Context for OrderLabelPrintScreen, to print one order's box labels."""
    context = context.copy()
    context["label_order"] = {
        "name": order_name,
        "customer": {"displayName": buyer_name},
        "line_items": line_items,
    }
    return context


def send_registration_label(serial, code, sku=""):
    """Print a cable's registration label; returns a note saying what happened."""
    from greenlight.screens.registration_codes import print_registration_label
    from greenlight.hardware.interfaces import hardware_manager
    from greenlight.hardware.tsc_label_printer import CABLE_ROLL_MM
    printer = hardware_manager.get_label_printer(CABLE_ROLL_MM)
    if not printer or not printer.is_ready():
        return f" {code} [red]label NOT printed (no printer)[/red]"
    if not print_registration_label(printer, serial, code, sku):
        return f" {code} [red]label NOT printed[/red]"
    return f" {code} [green]label printed[/green]"


class CompletedOrderScreen(Screen):
    """A fulfilled or cancelled order's cables, view-only.

    Nothing gets assigned here: adding a cable to a shipped order is almost
    certainly a mistake. A wholesale order can still reprint its labels, to
    fix a mislabeled box. Reprints only reuse a code the cable already has, and
    only for a cable on this order.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        order_id = self.context.get("order_id", "")
        order_name = self.context.get("order_name", "")
        line_items = self.context.get("line_items", [])
        dealer = self.context.get("dealer_name")
        wholesale = bool(self.context.get("company_gid"))
        customer_name = (self.context.get("selected_customer") or {}).get(
            "displayName") or "—"
        who = (f"[bold magenta]Wholesale:[/bold magenta] {dealer}" if wholesale
               else f"[bold cyan]Customer:[/bold cyan] {customer_name}")

        found = db.get_cables_for_orders([order_id])
        cables = None if found is None else found.get(order_id, [])
        note = ""

        while True:
            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(
                self._body(order_name, who, line_items, cables, note,
                           cancelled=self.context.get("cancelled", False)))

            if not wholesale:
                self.ui.layout["footer"].update(Panel(
                    "[cyan]'q'[/cyan] = back", title="Completed order"))
                self.ui.render()
                self.ui.wait_back()
                return ScreenResult(NavigationAction.POP)

            self.ui.layout["footer"].update(Panel(
                "Scan a cable to reprint its registration label | "
                "[cyan]'l'[/cyan] = box labels | [cyan]'q'[/cyan] = back",
                title="Completed order"))
            self.ui.render()

            serial_input = self.ui.get_serial_number_scan_or_manual()
            if not serial_input or serial_input.lower() == "q":
                return ScreenResult(NavigationAction.POP)
            if serial_input.lower() == "l":
                from greenlight.screens.order_labels import OrderLabelPrintScreen
                return ScreenResult(
                    NavigationAction.PUSH, OrderLabelPrintScreen,
                    box_label_context(self.context, order_name, dealer, line_items))
            note = self._reprint(serial_input, cables)

    @staticmethod
    def _body(order_name, who, line_items, cables, note, cancelled=False):
        from rich.console import Group
        lines = f"{who}\n[bold cyan]Order:[/bold cyan] {order_name}"
        if cancelled:
            lines += "\n\n[yellow]This order was cancelled.[/yellow]"
        if cables is None:
            lines += "\n\n[red]Couldn't read this order's cables from the database.[/red]"
        elif not cables and not cancelled:
            lines += ("\n\n[dim]No cables were scanned against this order. "
                      "It may have shipped without scanning.[/dim]")
        if note:
            lines += f"\n\n{note}"
        table, _ = order_progress_table(line_items, cables or [], closed=True)
        parts = [lines, "", table]
        others = other_cables(line_items, cables or [])
        if others:
            parts += ["", "[bold]Other cables on this order[/bold]"]
            parts += [f"  {c['serial_number']}  {c['variant_sku']}"
                      for c in sorted(others, key=lambda c: c["serial_number"])]
        return Panel(Group(*parts), title=f"Completed Order {order_name}")

    @staticmethod
    def _reprint(serial_input, cables):
        """Reprint a label if this cable is on this order. Changes no records."""
        from greenlight.db import validate_serial_number, format_serial_number
        valid, error = validate_serial_number(serial_input)
        if not valid:
            return f"[red]Invalid serial number: {error}[/red]"
        serial = format_serial_number(serial_input)
        match = next((c for c in cables or [] if c["serial_number"] == serial), None)
        if not match:
            return (f"[red]Cable {serial} isn't on this order. "
                    f"Nothing was changed.[/red]")
        record = db.get_audio_cable(serial) or {}
        code = record.get("registration_code")
        if not code:
            return f"[yellow]Cable {serial} has no registration code.[/yellow]"
        return serial + send_registration_label(serial, code,
                                                match.get("variant_sku") or "")


class OrderFulfillScanScreen(Screen):
    """Scan cables to fulfill a specific order with SKU validation and progress tracking.

    Website orders: each cable is checked against the line items and assigned
    to the customer. That is the whole job.

    Wholesale orders (`company_gid` in context): each cable is assigned to the
    dealer instead, leaving shopify_gid for its end buyer to register, and its
    registration label prints as it is scanned -- the code belongs to that one
    cable, so it goes on as the cable is in hand. A cable that already had a
    code (coded under `w`) doesn't print again on its first scan; scanning a
    cable already in the order reprints its label. `l` goes to the box labels
    (side + Prop 65 on the 1" printer, UPC on the 2"), which belong to the
    order, not a cable.
    """
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        customer_name = customer.get("displayName", "Customer")
        customer_gid = customer.get("id", "")
        company_gid = self.context.get("company_gid")
        location_gid = self.context.get("location_gid")
        wholesale = bool(company_gid)
        order_id = self.context.get("order_id", "")
        order_name = self.context.get("order_name", "")
        line_items = self.context.get("line_items", [])
        scanned_cables = self.context.get("scanned_cables", [])

        # Build line_item_skus list for validation
        line_item_skus = [item['sku'] for item in line_items]

        # Get already-assigned cables for this order (from DB, includes prior sessions)
        # Shopify line items carry variant SKU strings, which is what they match on.
        existing_order_cables = db.get_cables_for_order(order_id)
        progress_table, all_complete = order_progress_table(line_items, existing_order_cables)

        # Build body content
        if wholesale:
            dealer = self.context.get("dealer_name") or company_gid
            header_text = f"[bold magenta]Wholesale:[/bold magenta] {dealer}\n"
        else:
            header_text = f"[bold cyan]Customer:[/bold cyan] {customer_name}\n"
        header_text += f"[bold cyan]Order:[/bold cyan] {order_name}\n"

        if scanned_cables:
            header_text += f"\n[bold magenta]Recently scanned:[/bold magenta]"
            for cable_info in scanned_cables[-5:]:
                header_text += f"\n  • {cable_info}"

        if all_complete:
            header_text += "\n\n[bold green]✅ All line items fulfilled![/bold green]"

        from rich.console import Group
        body_content = Group(header_text, "", progress_table)

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(body_content, title=f"Fulfill Order {order_name}"))

        prompt = ("[bold green]Order complete![/bold green]" if all_complete
                  else "[cyan]Scan cable barcode[/cyan]")
        footer = f"{prompt} | "
        if existing_order_cables:
            footer += "[cyan]'r'[/cyan] = replace a cable | "
        if wholesale:
            footer += "[cyan]'l'[/cyan] = box labels | "
        footer += "[cyan]'q'[/cyan] = back"
        if wholesale:
            footer += ("\n[dim]To reprint a registration label, scan that cable "
                       "again.[/dim]")
        self.ui.layout["footer"].update(Panel(footer, title="Fulfillment"))
        self.ui.render()

        # Get serial number input
        serial_input = self.ui.get_serial_number_scan_or_manual()

        if not serial_input or serial_input.lower() == 'q':
            return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

        if wholesale and serial_input.lower() == 'l':
            from greenlight.screens.order_labels import OrderLabelPrintScreen
            return ScreenResult(
                NavigationAction.PUSH, OrderLabelPrintScreen,
                box_label_context(self.context, order_name,
                                  self.context.get("dealer_name") or customer_name,
                                  line_items))

        if serial_input.lower() == 'r':
            if existing_order_cables:
                self._take_off_order(existing_order_cables, scanned_cables, wholesale)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen,
                                {**self.context, "scanned_cables": scanned_cables})

        # Validate serial number
        from greenlight.db import validate_serial_number, format_serial_number
        valid, err_msg = validate_serial_number(serial_input)
        if not valid:
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Invalid serial number: {err_msg}[/red]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            time.sleep(ERROR_DISPLAY_SEC)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        formatted_serial = format_serial_number(serial_input)

        # Attempt assignment
        result = db.assign_cable_to_order(formatted_serial, customer_gid, order_id,
                                          line_item_skus, company_gid=company_gid,
                                          location_gid=location_gid,
                                          line_quantities=line_quantities(line_items))

        new_context = self.context.copy()

        if result.get('error') == 'line_full':
            self._offer_replacement(formatted_serial, result['sku'], result['quantity'],
                                    scanned_cables, wholesale)
            new_context["scanned_cables"] = scanned_cables
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, new_context)

        if result.get('success'):
            cable_sku = result.get('sku', '')
            note = f"{formatted_serial} ({cable_sku})"
            if wholesale:
                note += self._registration_label(formatted_serial, cable_sku)
            scanned_cables.append(note)
            new_context["scanned_cables"] = scanned_cables
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, new_context)

        if wholesale and result.get('error') == 'duplicate':
            scanned_cables.append(f"{formatted_serial} reprint"
                                  + self._registration_label(formatted_serial,
                                                             reprint=True))
            new_context["scanned_cables"] = scanned_cables
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, new_context)

        # Handle errors
        error_type = result.get('error')

        if error_type == 'not_found':
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Cable {formatted_serial} not found in database[/red]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            time.sleep(ERROR_DISPLAY_SEC)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'duplicate':
            self.ui.layout["body"].update(Panel(
                f"[yellow]⚠️  Cable {formatted_serial} is already scanned for this order[/yellow]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            time.sleep(ERROR_DISPLAY_SEC)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'already_assigned_order':
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Cable {formatted_serial} is assigned to a different order[/red]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            time.sleep(ERROR_DISPLAY_SEC)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'assigned_no_order':
            # Cable assigned to customer without order - ask to override
            existing_gid = result.get('existing_customer_gid', '')
            existing_customer_name = "another customer"
            try:
                if existing_gid:
                    customer_numeric_id = existing_gid.split('/')[-1]
                    existing_customer = shopify_client.get_customer_by_id(customer_numeric_id)
                    if existing_customer:
                        existing_customer_name = existing_customer.get('displayName') or "another customer"
            except:
                pass

            self.ui.layout["body"].update(Panel(
                f"[yellow]⚠️  Cable {formatted_serial} is assigned to {existing_customer_name} (no order)[/yellow]\n\n"
                f"Override and assign to this order?",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel(
                "[green]y[/green] = Override | [cyan]n[/cyan] = Skip",
                title="Override?"
            ))
            self.ui.render()

            try:
                choice = self.ui.console.input("").strip().lower()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

            if choice in ('y', 'yes'):
                # Need to also validate SKU before force-assigning
                # Re-check SKU by looking up the cable
                cable_record = db.get_audio_cable(formatted_serial)
                if cable_record:
                    cable_sku = cable_record.get('sku', '')
                    if cable_sku not in line_item_skus:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ SKU mismatch: cable is {cable_sku}, not in order[/red]",
                            title=f"Fulfill Order {order_name}"
                        ))
                        self.ui.layout["footer"].update(Panel("", title=""))
                        self.ui.render()
                        time.sleep(ERROR_DISPLAY_SEC)
                        return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)
                    on_line = sum(1 for c in existing_order_cables
                                  if c['variant_sku'] == cable_sku)
                    if on_line >= line_quantities(line_items).get(cable_sku, 0):
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ {cable_sku} is already full on this order. "
                            f"Press 'r' to take a cable off first.[/red]",
                            title=f"Fulfill Order {order_name}"
                        ))
                        self.ui.layout["footer"].update(Panel("", title=""))
                        self.ui.render()
                        time.sleep(ERROR_DISPLAY_SEC)
                        return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

                override_result = db.force_assign_cable_to_order(
                    formatted_serial, customer_gid, order_id,
                    company_gid=company_gid, location_gid=location_gid)
                if override_result.get('success'):
                    note = f"{formatted_serial} (override)"
                    if wholesale:
                        note += self._registration_label(formatted_serial)
                    scanned_cables.append(note)
                    new_context["scanned_cables"] = scanned_cables
                    return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, new_context)
                else:
                    self.ui.layout["body"].update(Panel(
                        f"[red]❌ Error: {override_result.get('message', 'Unknown')}[/red]",
                        title=f"Fulfill Order {order_name}"
                    ))
                    self.ui.layout["footer"].update(Panel("", title=""))
                    self.ui.render()
                    time.sleep(ERROR_DISPLAY_SEC)

            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'sku_mismatch':
            cable_sku = result.get('cable_sku', 'unknown')
            self.ui.layout["body"].update(Panel(
                f"[red]❌ SKU mismatch![/red]\n\n"
                f"Cable SKU: [yellow]{cable_sku}[/yellow]\n"
                f"Order expects: {', '.join(line_item_skus)}",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            time.sleep(ERROR_DISPLAY_SEC)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        else:
            # Generic error
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Error: {result.get('message', 'Unknown error')}[/red]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            time.sleep(ERROR_DISPLAY_SEC)
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

    def _offer_replacement(self, new_serial, sku, quantity, scanned_cables, wholesale):
        """A cable was scanned for a full line: is it replacing one of them?

        Nothing changes unless the operator picks a cable, so a stray scan is
        harmless. The new cable goes on first: if that fails, the old one is
        still on the order, and if taking the old one off fails, the order
        shows one too many rather than losing track of a cable.
        """
        order_id = self.context.get("order_id", "")
        cables = [c for c in db.get_cables_for_order(order_id)
                  if c["variant_sku"] == sku]
        old = self._choose_cable(
            "Line Full",
            f"[yellow]{sku} is full ({len(cables)}/{quantity}).[/yellow] "
            f"Is {new_serial} replacing one of these?",
            cables, "'q' = no, leave the order as it is")
        if not old:
            scanned_cables.append(f"{new_serial} [yellow]not added, {sku} is full[/yellow]")
            return

        result = db.assign_cable_to_order(
            new_serial, self.context.get("selected_customer", {}).get("id", ""),
            order_id, [sku], company_gid=self.context.get("company_gid"),
            location_gid=self.context.get("location_gid"))
        if not result.get('success'):
            scanned_cables.append(f"{new_serial} [red]not added: "
                                  f"{result.get('message', 'unknown error')}[/red]")
            return

        note = f"{new_serial} ({sku}) replaces {old['serial_number']}"
        if wholesale:
            note += self._registration_label(new_serial, sku)
        scanned_cables.append(note)
        scanned_cables.append(self._release_cable(old, wholesale))

    def _take_off_order(self, cables, scanned_cables, wholesale):
        """`r`: take a cable off, then its replacement is scanned as normal."""
        old = self._choose_cable(
            "Replace a Cable", "Which cable is coming off this order?",
            cables, "'q' = cancel")
        if old:
            scanned_cables.append(self._release_cable(old, wholesale))

    def _choose_cable(self, title, intro, cables, cancel_hint):
        """One of `cables`, chosen by number or scanned, or None for `q`."""
        note = ""
        while True:
            table = Table(show_header=True, header_style="bold cyan")
            table.add_column("#", style="green", width=3)
            table.add_column("Cable", style="white")
            table.add_column("SKU", style="dim")
            for i, cable in enumerate(cables, 1):
                table.add_row(str(i), cable["serial_number"], cable["variant_sku"])

            from rich.console import Group
            # The note goes above the table so a short terminal can't clip it.
            parts = [intro, note, table] if note else [intro, "", table]
            self.ui.layout["body"].update(Panel(Group(*parts), title=title))
            self.ui.layout["footer"].update(Panel(
                f"Enter a number, or scan the cable | [cyan]{cancel_hint}[/cyan]",
                title=title))
            self.ui.render()

            choice = self.ui.get_serial_number_scan_or_manual()
            if not choice or choice.lower() == "q":
                return None
            cable = pick_cable(choice, cables)
            if cable:
                return cable
            note = f"[red]{choice} isn't one of these.[/red]"

    def _release_cable(self, cable, wholesale):
        """Take a cable off the order and back into stock; returns a note."""
        serial = cable["serial_number"]
        result = db.unassign_cable(serial, channel="wholesale" if wholesale else "retail")
        if not result.get('success'):
            return (f"{serial} [red]still on this order: "
                    f"{result.get('message', 'unknown error')}[/red]")
        try:
            record = db.get_audio_cable(serial)
            if record:
                ok, error = shopify_client.sync_inventory_for_cable(record)
                if not ok:
                    logger.warning("Shopify inventory sync failed for %s: %s", serial, error)
        except Exception as e:
            logger.warning("Shopify inventory sync failed for %s: %s", serial, e)
        note = f"{serial} off this order, back in stock."
        if wholesale:
            note += " [yellow]Remove its old label.[/yellow]"
        return note

    def _registration_label(self, serial, sku="", reprint=False):
        """Code the cable (reusing an existing code) and print its label.

        A cable that already had a code -- coded under `w` for stock, say --
        most likely already wears its label, so its first scan into the order
        doesn't print another. `reprint` (a rescan) prints regardless.

        Returns a short note for the recently-scanned list, so a label that
        did not print is visible right next to the cable it belongs to.
        """
        from greenlight.screens.registration_codes import ensure_registration_code
        code, created, error = ensure_registration_code(serial)
        if not code:
            return f" [red]no code: {error}[/red]"
        if not created and not reprint:
            return f" {code} [yellow]already coded, rescan to reprint[/yellow]"
        return send_registration_label(serial, code, sku)


class AssignCablesScreen(Screen):
    """Scan and assign cables to a customer"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        customer_name = customer.get("displayName", "Customer")
        customer_gid = customer.get("id", "")

        # Track assigned cables in this session
        assigned_cables = self.context.get("assigned_cables", [])

        # Display currently assigned cables count
        existing_cables = db.get_cables_for_customer(customer_gid)
        total_cables = len(existing_cables)

        info_text = f"""[bold cyan]Customer:[/bold cyan] {customer_name}
[bold cyan]Shopify ID:[/bold cyan] {customer_gid}

[bold yellow]Cables already assigned:[/bold yellow] {total_cables}
[bold green]Cables assigned this session:[/bold green] {len(assigned_cables)}

[dim]Scan cable barcode or enter serial number[/dim]
[dim]Press 'q' to finish and go back[/dim]"""

        if assigned_cables:
            info_text += "\n\n[bold magenta]Recently assigned:[/bold magenta]"
            for cable in assigned_cables[-5:]:  # Show last 5
                info_text += f"\n  • {cable}"

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(info_text, title="Assign Cables to Customer"))
        self.ui.layout["footer"].update(Panel(
            "[cyan]Scan or enter serial number (or 'q' to finish)[/cyan]",
            title="Cable Assignment"
        ))
        self.ui.render()

        # Use shared scanner method
        serial_input = self.ui.get_serial_number_scan_or_manual()

        if not serial_input or serial_input.lower() == 'q':
            return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

        # Assign the cable to the customer
        self.ui.layout["body"].update(Panel(
            f"[yellow]Assigning cable {serial_input} to {customer_name}...[/yellow]",
            title="Assign Cables to Customer"
        ))
        self.ui.render()

        result = db.assign_cable_to_customer(serial_input, customer_gid)

        if result.get('success'):
            # Successfully assigned
            assigned_serial = result['serial_number']
            assigned_cables.append(assigned_serial)

            # Update context with new assigned cables list
            new_context = self.context.copy()
            new_context["assigned_cables"] = assigned_cables

            # Show success message briefly
            self.ui.layout["body"].update(Panel(
                f"[bold green]✅ Cable {assigned_serial} assigned to {customer_name}![/bold green]",
                title="Success"
            ))
            self.ui.render()

            # Continue to next scan
            return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, new_context)

        else:
            # Error occurred
            error_type = result.get('error')
            error_msg = result.get('message')

            if error_type == 'not_found':
                error_display = f"[red]❌ Cable not found[/red]\n\n{error_msg}"

                self.ui.layout["body"].update(Panel(error_display, title="Cable Assignment"))
                self.ui.layout["footer"].update(Panel("", title=""))
                self.ui.render()
                time.sleep(ERROR_DISPLAY_SEC)

                # Continue scanning
                return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)

            elif error_type == 'already_assigned':
                # Cable is already assigned - ask if user wants to reassign
                existing_gid = result.get('existing_customer_gid', 'unknown')

                # Try to get existing customer name
                existing_customer_name = "another customer"
                try:
                    if existing_gid and existing_gid != 'unknown':
                        customer_numeric_id = existing_gid.split('/')[-1]
                        existing_customer = shopify_client.get_customer_by_id(customer_numeric_id)
                        if existing_customer:
                            existing_customer_name = existing_customer.get('displayName') or "another customer"
                except:
                    pass  # If we can't get the customer, just use "another customer"

                reassign_prompt = f"""[yellow]⚠️  Cable Already Assigned[/yellow]

Cable [bold]{serial_input}[/bold] is currently assigned to:
[cyan]{existing_customer_name}[/cyan]

Do you want to reassign it to [bold green]{customer_name}[/bold green]?"""

                self.ui.layout["body"].update(Panel(reassign_prompt, title="Cable Already Assigned"))
                self.ui.layout["footer"].update(Panel(
                    "[green]y[/green] = Reassign to this customer | [cyan]n[/cyan] = Skip | [yellow]q[/yellow] = Quit assignment",
                    title="Reassign?"
                ))
                self.ui.render()

                try:
                    choice = self.ui.console.input("").strip().lower()
                except KeyboardInterrupt:
                    return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))

                if choice == 'y' or choice == 'yes':
                    # Force reassignment
                    self.ui.layout["body"].update(Panel(
                        f"[yellow]Reassigning cable {serial_input}...[/yellow]",
                        title="Reassigning Cable"
                    ))
                    self.ui.render()

                    reassign_result = db.force_reassign_cable(serial_input, customer_gid)

                    if reassign_result.get('success'):
                        assigned_serial = reassign_result['serial_number']
                        assigned_cables.append(assigned_serial)

                        new_context = self.context.copy()
                        new_context["assigned_cables"] = assigned_cables

                        self.ui.layout["body"].update(Panel(
                            f"[bold green]✅ Cable {assigned_serial} reassigned to {customer_name}![/bold green]",
                            title="Success"
                        ))
                        self.ui.render()
                        time.sleep(1)

                        return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, new_context)
                    else:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ Error reassigning cable: {reassign_result.get('message', 'Unknown error')}[/red]",
                            title="Error"
                        ))
                        self.ui.render()
                        time.sleep(ERROR_DISPLAY_SEC)

                        return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)

                elif choice == 'q':
                    # Quit assignment and go back to main hub
                    return ScreenResult(NavigationAction.POP, pop_to=_assign_pop_target(self.context))
                else:
                    # Skip this cable, continue scanning
                    return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)

            else:
                error_display = f"[red]❌ Error[/red]\n\n{error_msg}"

                self.ui.layout["body"].update(Panel(error_display, title="Cable Assignment"))
                self.ui.layout["footer"].update(Panel("", title=""))
                self.ui.render()
                time.sleep(ERROR_DISPLAY_SEC)

                # Continue scanning
                return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)
