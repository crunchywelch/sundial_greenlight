import time
import logging
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction

logger = logging.getLogger(__name__)


class SettingsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        menu_items = [
            "Database Settings",
            "User Management",
            "System Information",
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Configure system settings and preferences", title="Settings"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Settings"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice == "1":
            return ScreenResult(NavigationAction.PUSH, DatabaseSettingsScreen, self.context)
        elif choice == "2":
            return ScreenResult(NavigationAction.PUSH, UserManagementScreen, self.context)
        elif choice == "3":
            return ScreenResult(NavigationAction.PUSH, SystemInfoScreen, self.context)
        elif choice in ["4", "q"]:
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, SettingsScreen, self.context)


class DatabaseSettingsScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Database settings functionality coming soon", title="Database Settings"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)



class UserManagementScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("User management functionality coming soon", title="User Management"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class SystemInfoScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("System information functionality coming soon", title="System Information"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)
