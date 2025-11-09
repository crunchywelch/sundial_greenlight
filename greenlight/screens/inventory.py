from rich.panel import Panel

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction


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
            return ScreenResult(NavigationAction.PUSH, ViewInventoryScreen, self.context)
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


class ViewInventoryScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("View inventory functionality coming soon", title="View Inventory"))
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