"""Order fulfillment screens: Customer lookup and order processing"""
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
            "View Orders",
            "Scan to Fulfill",
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
        elif choice == "2":
            return ScreenResult(NavigationAction.PUSH, ViewOrdersScreen, self.context)
        elif choice == "3":
            return ScreenResult(NavigationAction.PUSH, ScanToFulfillScreen, self.context)
        elif choice in ["4", "q"]:
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

        footer_text = "[cyan]Enter number to view details, 'n' for new search, or 'q' to go back[/cyan]"
        self.ui.layout["footer"].update(Panel(footer_text, title="Select Customer"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP, pop_count=2)

        if choice == 'q':
            # Pop 2 screens to go back to order fulfillment main menu
            return ScreenResult(NavigationAction.POP, pop_count=2)
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

        footer_text = "[cyan]Press 'o' for orders, 'c' to assign cables, or 'enter' to go back[/cyan]"
        self.ui.layout["footer"].update(Panel(footer_text, title=""))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choice: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice == 'o':
            # Fetch and display orders
            return ScreenResult(NavigationAction.PUSH, CustomerOrdersScreen, self.context)
        elif choice == 'c':
            # Assign cables to customer
            return ScreenResult(NavigationAction.PUSH, AssignCablesScreen, self.context)

        return ScreenResult(NavigationAction.POP)

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
            # Success - show confirmation
            self.ui.layout["body"].update(Panel(
                f"[bold green]✅ Cable Assigned Successfully![/bold green]\n\n"
                f"Cable: [yellow]{cable_serial}[/yellow] ({cable_sku})\n"
                f"Customer: [cyan]{customer_name}[/cyan]\n"
                f"Email: {customer.get('email', 'N/A')}\n\n"
                f"[dim]Press enter to return to cable scanning[/dim]",
                title="Assignment Complete",
                style="green"
            ))
            self.ui.layout["footer"].update(Panel("", title=""))
            self.ui.render()
            self.ui.console.input()

            # Pop back to cable scan screen
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
                    from greenlight.db import pg_pool

                    self.ui.layout["body"].update(Panel(
                        f"[yellow]Reassigning cable {cable_serial}...[/yellow]",
                        title="Reassigning Cable"
                    ))
                    self.ui.render()

                    try:
                        conn = pg_pool.getconn()
                        with conn:
                            with conn.cursor() as cur:
                                cur.execute("""
                                    UPDATE audio_cables
                                    SET shopify_gid = %s
                                    WHERE serial_number = %s
                                    RETURNING serial_number
                                """, (customer_gid, cable_serial))
                                updated = cur.fetchone()
                                conn.commit()

                                if updated:
                                    self.ui.layout["body"].update(Panel(
                                        f"[bold green]✅ Cable Reassigned Successfully![/bold green]\n\n"
                                        f"Cable: [yellow]{cable_serial}[/yellow] ({cable_sku})\n"
                                        f"Customer: [cyan]{customer_name}[/cyan]\n\n"
                                        f"[dim]Press enter to return to cable scanning[/dim]",
                                        title="Reassignment Complete",
                                        style="green"
                                    ))
                                    self.ui.layout["footer"].update(Panel("", title=""))
                                    self.ui.render()
                                    self.ui.console.input()

                                    from greenlight.screens.cable import ScanCableLookupScreen
                                    return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

                        pg_pool.putconn(conn)
                    except Exception as e:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ Error reassigning cable: {e}[/red]\n\n[dim]Press enter to return[/dim]",
                            title="Error"
                        ))
                        self.ui.layout["footer"].update(Panel("", title=""))
                        self.ui.render()
                        self.ui.console.input()

                        if 'conn' in locals():
                            pg_pool.putconn(conn)

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


class ViewOrdersScreen(Screen):
    """View all orders (placeholder)"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "View all orders functionality coming soon",
            title="View Orders"
        ))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()

        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class ScanToFulfillScreen(Screen):
    """Scan cables to fulfill orders (placeholder)"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "Scan to fulfill functionality coming soon",
            title="Scan to Fulfill"
        ))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()

        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


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
            # Go back to customer lookup screen
            return ScreenResult(NavigationAction.POP, pop_to=CustomerLookupScreen)

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
                    return ScreenResult(NavigationAction.POP, pop_to=CustomerLookupScreen)

                if choice == 'y' or choice == 'yes':
                    # Force reassignment by updating the database directly
                    # First get the cable record, then update it
                    from greenlight.db import pg_pool

                    self.ui.layout["body"].update(Panel(
                        f"[yellow]Reassigning cable {serial_input}...[/yellow]",
                        title="Reassigning Cable"
                    ))
                    self.ui.render()

                    try:
                        conn = pg_pool.getconn()
                        with conn:
                            with conn.cursor() as cur:
                                # Update the cable assignment (override existing)
                                cur.execute("""
                                    UPDATE audio_cables
                                    SET shopify_gid = %s
                                    WHERE serial_number = %s
                                    RETURNING serial_number, sku
                                """, (customer_gid, serial_input))
                                updated = cur.fetchone()
                                conn.commit()

                                if updated:
                                    assigned_serial = updated[0]
                                    assigned_cables.append(assigned_serial)

                                    # Update context
                                    new_context = self.context.copy()
                                    new_context["assigned_cables"] = assigned_cables

                                    # Show success
                                    self.ui.layout["body"].update(Panel(
                                        f"[bold green]✅ Cable {assigned_serial} reassigned to {customer_name}![/bold green]",
                                        title="Success"
                                    ))
                                    self.ui.render()

                                    import time
                                    time.sleep(1)

                                    # Continue to next scan
                                    return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, new_context)

                        pg_pool.putconn(conn)
                    except Exception as e:
                        self.ui.layout["body"].update(Panel(
                            f"[red]❌ Error reassigning cable: {e}[/red]\n\n[dim]Press enter to continue[/dim]",
                            title="Error"
                        ))
                        self.ui.render()
                        self.ui.console.input()

                        if 'conn' in locals():
                            pg_pool.putconn(conn)

                        return ScreenResult(NavigationAction.REPLACE, AssignCablesScreen, self.context)

                elif choice == 'q':
                    # Quit assignment and go back
                    return ScreenResult(NavigationAction.POP, pop_to=CustomerLookupScreen)
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
