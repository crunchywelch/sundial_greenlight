"""Order fulfillment screens: Customer lookup, order processing, and cable assignment"""
from rich.panel import Panel
from rich.table import Table

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight import shopify_client
from greenlight import db


class FulfillOrdersScreen(Screen):
    """Main order fulfillment menu"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        menu_items = [
            "Lookup Customer",
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Process customer orders and fulfillment", title="Order Fulfillment"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Operations"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice == "1":
            return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, self.context)
        elif choice in ["2", "q"]:
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, FulfillOrdersScreen, self.context)


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

        customers = shopify_client.search_customers_by_name(search_name)

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
        table.add_column("Email", style="dim")
        table.add_column("Orders", justify="right", style="yellow")
        table.add_column("Total Spent", justify="right", style="green")

        for i, customer in enumerate(customers, 1):
            name = customer.get("displayName") or "N/A"
            email = customer.get("email") or "N/A"
            num_orders = str(customer.get("numberOfOrders") or 0)

            amount_spent = customer.get("amountSpent") or {}
            if amount_spent and amount_spent.get("amount"):
                spent = f"${float(amount_spent['amount']):.2f}"
            else:
                spent = "$0.00"

            table.add_row(str(i), name, email, num_orders, spent)

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
            from greenlight.screens.cable import ScanCableLookupScreen
            return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

        # Auto-select if only one result and user pressed Enter
        if choice == '' and len(customers) == 1:
            choice = '1'

        if choice == 'q':
            from greenlight.screens.cable import ScanCableLookupScreen
            return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)
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
        name = customer.get("displayName") or "N/A"
        email = customer.get("email") or "N/A"

        # Try to get phone from customer level, then from address
        phone = customer.get("phone")
        address = customer.get("defaultAddress")
        if not phone and address:
            phone = address.get("phone")
        phone = phone or "N/A"

        # Convert numberOfOrders to int (Shopify returns it as string)
        num_orders_raw = customer.get("numberOfOrders") or 0
        num_orders = int(num_orders_raw) if num_orders_raw else 0

        amount_spent = customer.get("amountSpent", {})
        if amount_spent and amount_spent.get("amount"):
            spent = f"${float(amount_spent['amount']):.2f} {amount_spent.get('currencyCode', 'USD')}"
        else:
            spent = "$0.00"

        # Format address for display
        if address:
            addr_lines = [
                address.get("address1") or "",
                address.get("address2") or "",
                f"{address.get('city') or ''}, {address.get('province') or ''} {address.get('zip') or ''}",
                address.get("country") or ""
            ]
            address_text = "\n".join([line for line in addr_lines if line and line.strip()])
        else:
            address_text = "No address on file"

        # Fetch most recent order and assigned cables
        customer_id = customer.get("id", "")
        recent_orders = shopify_client.get_customer_orders(customer_id, limit=1)
        assigned_cables = db.get_cables_for_customer(customer_id)

        last_order_text = ""
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
            for item_edge in line_items[:3]:  # Show first 3 items
                item = item_edge.get("node") or {}
                title = item.get("title") or "Unknown"
                qty = item.get("quantity") or 0
                items_summary.append(f"  • {title} (x{qty})")

            if len(line_items) > 3:
                items_summary.append(f"  • ... and {len(line_items) - 3} more items")

            last_order_text = f"""
[bold magenta]Last Order:[/bold magenta] {order_name} - {order_date}
[bold magenta]Status:[/bold magenta] {order_status} / {order_financial}
[bold magenta]Total:[/bold magenta] {order_total}
[bold magenta]Items:[/bold magenta]
{chr(10).join(items_summary) if items_summary else "  No items"}
"""
        else:
            # No orders returned - but check if customer has orders
            if num_orders > 0:
                last_order_text = f"\n[dim]Customer has {num_orders} order(s) but they are not accessible via API[/dim]\n[dim](May be from a different sales channel or restricted status)[/dim]"
            else:
                last_order_text = "\n[dim]No orders yet[/dim]"

        # Format assigned cables display
        cables_text = f"\n[bold magenta]Assigned Cables:[/bold magenta] {len(assigned_cables)}"
        if assigned_cables:
            cables_text += "\n"
            for cable in assigned_cables[:5]:  # Show first 5
                # For MISC cables, show the custom description
                if cable['sku'].endswith('-MISC') and cable.get('description'):
                    cable_desc = f"{cable['series']} {cable['length']}ft - {cable['description']}"
                else:
                    cable_desc = f"{cable['series']} {cable['length']}ft {cable['color_pattern']}"
                cables_text += f"\n  • {cable['serial_number']} - {cable_desc}"

            if len(assigned_cables) > 5:
                cables_text += f"\n  • ... and {len(assigned_cables) - 5} more"
        else:
            cables_text += "\n  [dim]No cables assigned yet[/dim]"

        customer_info = f"""[bold cyan]Name:[/bold cyan] {name}
[bold cyan]Email:[/bold cyan] {email}
[bold cyan]Phone:[/bold cyan] {phone}

[bold yellow]Order Count:[/bold yellow] {num_orders}
[bold yellow]Total Spent:[/bold yellow] {spent}

[bold green]Address:[/bold green]
{address_text}
{last_order_text}
{cables_text}
"""

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(customer_info, title="Customer Details"))

        footer_parts = [
            "[cyan]'o'[/cyan] = orders",
            "[cyan]'c'[/cyan] = assign cables",
        ]
        if assigned_cables:
            footer_parts.append("[cyan]'u'[/cyan] = unassign cable")
        footer_parts.extend([
            "[cyan]'f'[/cyan] = fulfill order",
            "[cyan]Enter[/cyan] = back",
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
        elif choice == 'c':
            # Check for unfulfilled orders before allowing direct assignment
            orders = shopify_client.get_customer_orders(customer_id, limit=25)
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
        elif choice == 'f':
            return ScreenResult(NavigationAction.PUSH, OrderSelectionScreen, self.context)
        elif choice == '':
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
            from greenlight.screens.cable import ScanCableLookupScreen
            return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)
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
                    from greenlight.screens.cable import ScanCableLookupScreen
                    return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

                if choice == 'y' or choice == 'yes':
                    # Force reassignment
                    self.ui.layout["body"].update(Panel(
                        f"[yellow]Reassigning cable {cable_serial}...[/yellow]",
                        title="Reassigning Cable"
                    ))
                    self.ui.render()

                    reassign_result = db.force_reassign_cable(cable_serial, customer_gid)

                    if reassign_result.get('success'):
                        from greenlight.screens.cable import ScanCableLookupScreen
                        return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)
                    else:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ Error reassigning cable: {reassign_result.get('message', 'Unknown error')}[/red]\n\n[dim]Press enter to return[/dim]",
                            title="Error"
                        ))
                        self.ui.layout["footer"].update(Panel("", title=""))
                        self.ui.render()
                        self.ui.console.input()

                        from greenlight.screens.cable import ScanCableLookupScreen
                        return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

                else:
                    # Cancel or go back to scanning
                    from greenlight.screens.cable import ScanCableLookupScreen
                    return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

            else:
                # Other error
                error_display = f"[red]❌ Assignment Error[/red]\n\n{error_msg}\n\n[dim]Press enter to return[/dim]"

                self.ui.layout["body"].update(Panel(error_display, title="Assignment Failed"))
                self.ui.layout["footer"].update(Panel("", title=""))
                self.ui.render()
                self.ui.console.input()

                # Pop back to cable scan screen
                from greenlight.screens.cable import ScanCableLookupScreen
                return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)


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
            self.ui.layout["footer"].update(Panel("[cyan]Press Enter to go back[/cyan]", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.POP)

        # Build cable list table
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("#", style="green", width=3)
        table.add_column("Serial", style="white")
        table.add_column("Cable", style="dim")
        table.add_column("Tested", justify="center", style="yellow")

        for i, cable in enumerate(assigned_cables, 1):
            if cable['sku'].endswith('-MISC') and cable.get('description'):
                cable_desc = f"{cable['series']} {cable['length']}ft - {cable['description']}"
            else:
                cable_desc = f"{cable['series']} {cable['length']}ft {cable['color_pattern']}"
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

        # Perform unassignment
        result = db.unassign_cable(serial)

        if result.get('success'):
            self.ui.layout["body"].update(Panel(
                f"[green]Cable {serial} unassigned from {customer_name}[/green]\n\n"
                f"[dim]Press Enter to continue[/dim]",
                title="Unassigned"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"[red]Error: {result.get('message', 'Unknown error')}[/red]\n\n"
                f"[dim]Press Enter to continue[/dim]",
                title="Error"
            ))
        self.ui.layout["footer"].update(Panel("", title=""))
        self.ui.render()
        self.ui.console.input()

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

        orders = shopify_client.get_customer_orders(customer_id, limit=10)

        if not orders:
            self.ui.layout["body"].update(Panel(
                "[dim]No orders found for this customer[/dim]\n\n[cyan]Press enter to go back[/cyan]",
                title=f"Orders for {customer_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
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
        self.ui.layout["footer"].update(Panel(
            "[cyan]Press enter to go back[/cyan]",
            title=""
        ))
        self.ui.render()

        self.ui.console.input()
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

        orders = shopify_client.get_customer_orders(customer_id, limit=25)

        # Filter to unfulfilled/partially fulfilled orders
        unfulfilled_orders = []
        for order in orders:
            status = (order.get("displayFulfillmentStatus") or "").upper()
            if status in ("UNFULFILLED", "PARTIALLY_FULFILLED", ""):
                unfulfilled_orders.append(order)

        if not unfulfilled_orders:
            self.ui.layout["body"].update(Panel(
                f"[dim]No unfulfilled orders found for {customer_name}[/dim]\n\n[cyan]Press enter to go back[/cyan]",
                title="Order Selection"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
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
        order_id = selected_order.get("id", "")
        order_name = selected_order.get("name", "")

        line_items_raw = (selected_order.get("lineItems") or {}).get("edges") or []
        line_items = []
        for edge in line_items_raw:
            node = edge.get("node") or {}
            sku = node.get("sku")
            if sku:
                line_items.append({
                    'sku': sku,
                    'title': node.get("title") or "Unknown",
                    'quantity': node.get("quantity") or 0,
                })

        if not line_items:
            self.ui.layout["body"].update(Panel(
                "[red]No cable items (with SKUs) found in this order[/red]\n\n"
                "[dim]Press enter to go back[/dim]",
                title="Order Selection"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, OrderSelectionScreen, self.context)

        new_context = self.context.copy()
        new_context["order_id"] = order_id
        new_context["order_name"] = order_name
        new_context["line_items"] = line_items
        new_context["scanned_cables"] = []
        return ScreenResult(NavigationAction.PUSH, OrderFulfillScanScreen, new_context)


class OrderFulfillScanScreen(Screen):
    """Scan cables to fulfill a specific order with SKU validation and progress tracking"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        customer = self.context.get("selected_customer", {})
        customer_name = customer.get("displayName", "Customer")
        customer_gid = customer.get("id", "")
        order_id = self.context.get("order_id", "")
        order_name = self.context.get("order_name", "")
        line_items = self.context.get("line_items", [])
        scanned_cables = self.context.get("scanned_cables", [])

        # Build line_item_skus list for validation
        line_item_skus = [item['sku'] for item in line_items]

        # Get already-assigned cables for this order (from DB, includes prior sessions)
        existing_order_cables = db.get_cables_for_order(order_id)
        existing_skus_scanned = {}
        for cable in existing_order_cables:
            sku = cable['effective_sku']
            existing_skus_scanned[sku] = existing_skus_scanned.get(sku, 0) + 1

        # Build progress table
        progress_table = Table(show_header=True, header_style="bold cyan", expand=True)
        progress_table.add_column("SKU", style="white")
        progress_table.add_column("Title", style="dim")
        progress_table.add_column("Progress", justify="center", style="yellow")
        progress_table.add_column("Status", justify="center")

        all_complete = True
        for item in line_items:
            sku = item['sku']
            needed = item['quantity']
            scanned = existing_skus_scanned.get(sku, 0)
            progress_str = f"{scanned}/{needed}"

            if scanned >= needed:
                status = "[bold green]DONE[/bold green]"
            else:
                status = f"[yellow]{needed - scanned} remaining[/yellow]"
                all_complete = False

            progress_table.add_row(sku, item['title'], progress_str, status)

        # Build body content
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

        if all_complete:
            self.ui.layout["footer"].update(Panel(
                "[bold green]Order complete![/bold green] Press [cyan]'q'[/cyan] to go back, or continue scanning",
                title="Fulfillment"
            ))
        else:
            self.ui.layout["footer"].update(Panel(
                "[cyan]Scan cable barcode (or 'q' to go back)[/cyan]",
                title="Fulfillment"
            ))
        self.ui.render()

        # Get serial number input
        serial_input = self.ui.get_serial_number_scan_or_manual()

        if not serial_input or serial_input.lower() == 'q':
            from greenlight.screens.cable import ScanCableLookupScreen
            return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

        # Validate serial number
        from greenlight.db import validate_serial_number, format_serial_number
        valid, err_msg = validate_serial_number(serial_input)
        if not valid:
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Invalid serial number: {err_msg}[/red]\n\n[dim]Press enter to continue[/dim]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        formatted_serial = format_serial_number(serial_input)

        # Attempt assignment
        result = db.assign_cable_to_order(formatted_serial, customer_gid, order_id, line_item_skus)

        new_context = self.context.copy()

        if result.get('success'):
            effective_sku = result.get('effective_sku', '')
            scanned_cables.append(f"{formatted_serial} ({effective_sku})")
            new_context["scanned_cables"] = scanned_cables
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, new_context)

        # Handle errors
        error_type = result.get('error')

        if error_type == 'not_found':
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Cable {formatted_serial} not found in database[/red]\n\n"
                f"[dim]Press enter to continue scanning[/dim]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'duplicate':
            self.ui.layout["body"].update(Panel(
                f"[yellow]⚠️  Cable {formatted_serial} is already scanned for this order[/yellow]\n\n"
                f"[dim]Press enter to continue scanning[/dim]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'already_assigned_order':
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Cable {formatted_serial} is assigned to a different order[/red]\n\n"
                f"[dim]Press enter to continue scanning[/dim]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
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
                    effective_sku = cable_record.get('special_baby_shopify_sku') or cable_record.get('sku', '')
                    if effective_sku not in line_item_skus:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ SKU mismatch: cable is {effective_sku}, not in order[/red]\n\n"
                            f"[dim]Press enter to continue scanning[/dim]",
                            title=f"Fulfill Order {order_name}"
                        ))
                        self.ui.layout["footer"].update(Panel("", title=""))
                        self.ui.render()
                        self.ui.console.input()
                        return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

                override_result = db.force_assign_cable_to_order(formatted_serial, customer_gid, order_id)
                if override_result.get('success'):
                    scanned_cables.append(f"{formatted_serial} (override)")
                    new_context["scanned_cables"] = scanned_cables
                    return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, new_context)
                else:
                    self.ui.layout["body"].update(Panel(
                        f"[red]❌ Error: {override_result.get('message', 'Unknown')}[/red]\n\n"
                        f"[dim]Press enter to continue[/dim]",
                        title=f"Fulfill Order {order_name}"
                    ))
                    self.ui.layout["footer"].update(Panel("", title=""))
                    self.ui.render()
                    self.ui.console.input()

            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        elif error_type == 'sku_mismatch':
            cable_sku = result.get('cable_sku', 'unknown')
            self.ui.layout["body"].update(Panel(
                f"[red]❌ SKU mismatch![/red]\n\n"
                f"Cable SKU: [yellow]{cable_sku}[/yellow]\n"
                f"Order expects: {', '.join(line_item_skus)}\n\n"
                f"[dim]Press enter to continue scanning[/dim]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)

        else:
            # Generic error
            self.ui.layout["body"].update(Panel(
                f"[red]❌ Error: {result.get('message', 'Unknown error')}[/red]\n\n"
                f"[dim]Press enter to continue scanning[/dim]",
                title=f"Fulfill Order {order_name}"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, OrderFulfillScanScreen, self.context)


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
            from greenlight.screens.cable import ScanCableLookupScreen
            return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

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
                error_display = f"[red]❌ Cable not found[/red]\n\n{error_msg}\n\n[dim]Press enter to try again[/dim]"

                self.ui.layout["body"].update(Panel(error_display, title="Cable Assignment"))
                self.ui.layout["footer"].update(Panel("", title=""))
                self.ui.render()
                self.ui.console.input()

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
                    from greenlight.screens.cable import ScanCableLookupScreen
                    return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

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

                        import time
                        time.sleep(1)

                        return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, new_context)
                    else:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ Error reassigning cable: {reassign_result.get('message', 'Unknown error')}[/red]\n\n[dim]Press enter to continue[/dim]",
                            title="Error"
                        ))
                        self.ui.render()
                        self.ui.console.input()

                        return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)

                elif choice == 'q':
                    # Quit assignment and go back to main hub
                    from greenlight.screens.cable import ScanCableLookupScreen
                    return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)
                else:
                    # Skip this cable, continue scanning
                    return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)

            else:
                error_display = f"[red]❌ Error[/red]\n\n{error_msg}\n\n[dim]Press enter to try again[/dim]"

                self.ui.layout["body"].update(Panel(error_display, title="Cable Assignment"))
                self.ui.layout["footer"].update(Panel("", title=""))
                self.ui.render()
                self.ui.console.input()

                # Continue scanning
                return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)
