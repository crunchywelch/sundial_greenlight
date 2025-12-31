from rich.panel import Panel
from rich.table import Table

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.db import get_available_inventory, get_available_series


class InventoryScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        menu_items = [
            "View Inventory",
            "Add Items",
            "Update Stock",
            "Reports",
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Manage cable inventory and stock levels", title="Inventory Management"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Operations"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice == "1":
            return ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, self.context)
        elif choice == "2":
            return ScreenResult(NavigationAction.PUSH, AddItemsScreen, self.context)
        elif choice == "3":
            return ScreenResult(NavigationAction.PUSH, UpdateStockScreen, self.context)
        elif choice == "4":
            return ScreenResult(NavigationAction.PUSH, ReportsScreen, self.context)
        elif choice in ["5", "q"]:
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, InventoryScreen, self.context)


class SeriesSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        # Get available series
        series_list = get_available_series()

        if not series_list:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "[yellow]No series with available inventory[/yellow]",
                title="Select Series"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        # Build menu
        menu_items = series_list + ["Back (q)"]
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "Select a product series to view available inventory",
            title="Select Series"
        ))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Series"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")

        # Check if quit
        if choice in [str(len(menu_items)), "q"]:
            return ScreenResult(NavigationAction.POP)

        # Check if valid series choice
        try:
            choice_num = int(choice) - 1
            if 0 <= choice_num < len(series_list):
                selected_series = series_list[choice_num]
                context = self.context.copy()
                context["selected_series"] = selected_series
                return ScreenResult(NavigationAction.PUSH, ViewInventoryScreen, context)
        except ValueError:
            pass

        # Invalid choice - redisplay
        return ScreenResult(NavigationAction.REPLACE, SeriesSelectionScreen, self.context)


class ViewInventoryScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")

        # Fetch available inventory for the selected series
        inventory = get_available_inventory(series=selected_series)

        if not inventory:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"[yellow]No cables available in {selected_series} series[/yellow]",
                title="Available Inventory"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        # Group inventory by color pattern
        from collections import defaultdict
        grouped = defaultdict(list)
        for item in inventory:
            color_key = item['color_pattern'] or 'Unknown'
            grouped[color_key].append(item)

        # Create table (without Series and Color columns since they're in group headers)
        title = f"Available Inventory - {selected_series} Series" if selected_series else "Available Inventory"
        table = Table(title=title, show_header=True, header_style="bold cyan")
        table.add_column("SKU", style="green", width=14)
        table.add_column("Length", width=10)
        table.add_column("Connector", width=18)
        table.add_column("Count", justify="right", style="bold yellow", width=8)
        table.add_column("Description", width=40)

        # Add rows grouped by color pattern
        total_count = 0
        for color_pattern in sorted(grouped.keys()):
            items = grouped[color_pattern]
            color_count = sum(item['available_count'] for item in items)

            # Sort items by length (extract numeric part)
            def get_length_value(item):
                length_str = item.get('length', '') or ''
                try:
                    # Extract numeric part from strings like "3'", "10'", "15'"
                    return int(length_str.replace("'", "").strip())
                except (ValueError, AttributeError):
                    return 999  # Put items with no/invalid length at end

            items_sorted = sorted(items, key=get_length_value)

            # Add color header row
            table.add_row(
                f"[bold cyan]{color_pattern}[/bold cyan]",
                "",
                "",
                f"[bold cyan]{color_count}[/bold cyan]",
                "",
                style="bold cyan"
            )

            # Add items for this color
            for item in items_sorted:
                table.add_row(
                    item['sku'],
                    item['length'] or '',
                    item['connector_type'] or '',
                    str(item['available_count']),
                    item['description'] or ''
                )
                total_count += item['available_count']

            # Add blank row between color groups
            if color_pattern != sorted(grouped.keys())[-1]:
                table.add_row("", "", "", "", "")

        # Add total summary row
        table.add_row("", "", "[bold]TOTAL:[/bold]", f"[bold]{total_count}[/bold]", "", style="bold cyan")

        self.ui.header(operator)
        self.ui.layout["body"].update(table)
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()

        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class AddItemsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Add items functionality coming soon", title="Add Items"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class UpdateStockScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Update stock functionality coming soon", title="Update Stock"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class ReportsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Reports functionality coming soon", title="Reports"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)