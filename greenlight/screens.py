import os
import sys
from rich.panel import Panel

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import OPERATORS, APP_NAME, APP_SUBTITLE, EXIT_MESSAGE


class SplashScreen(Screen):
    def run(self) -> ScreenResult:
        """Combined splash screen and operator selection"""
        self.ui.console.clear()
        self.ui.header()

        # Load and display splash art
        splash_path = os.path.join(os.path.dirname(__file__), "art", "splash.txt")
        with open(splash_path, "r") as f:
            splash_text = f.read()

        self.ui.console.print(Panel(splash_text, style="bold green", subtitle=APP_SUBTITLE))

        # Show operator selection immediately below splash
        rows = [
            f"[green]{i + 1}.[/green] {name} ({code})"
            for i, (code, name) in enumerate(OPERATORS.items())
        ]

        self.ui.console.print()  # Empty line
        self.ui.console.print(Panel("\n".join(rows), title="[bold cyan]Select Operator[/bold cyan]"))

        codes = list(OPERATORS.keys())
        valid_choices = [str(i + 1) for i in range(len(codes))]
        valid_choices.append("q")
        choice_str = ",".join(valid_choices)

        try:
            choice = self.ui.console.input(f"\n[bold]Choose operator:[/bold] ({choice_str}) ")
        except KeyboardInterrupt:
            print(f"\n\n🛑 Exiting {APP_NAME}...")
            print(EXIT_MESSAGE)
            sys.exit(0)

        if choice == "q":
            return ScreenResult(NavigationAction.POP)
        elif choice in valid_choices:
            operator_code = codes[int(choice) - 1]
            return ScreenResult(NavigationAction.PUSH, MainMenuScreen, {"operator": operator_code})
        else:
            # Invalid choice - redisplay the same screen
            return ScreenResult(NavigationAction.REPLACE, SplashScreen)

class MainMenuScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        menu_items = [
            "Scan and Test Cables",
            "Fulfill Orders", 
            "Settings",
            "Exit (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("", title=""))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Operations"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ")
        except KeyboardInterrupt:
            print(f"\n\n🛑 Exiting {APP_NAME}...")
            print(EXIT_MESSAGE)
            sys.exit(0)
            
        if choice == "1":
            from greenlight.cable_screens import CableSelectionForIntakeScreen
            new_context = self.context.copy()
            new_context["selection_mode"] = "intake"
            return ScreenResult(NavigationAction.PUSH, CableSelectionForIntakeScreen, new_context)
        elif choice == "2":
            from greenlight.inventory_screens import InventoryScreen
            return ScreenResult(NavigationAction.PUSH, InventoryScreen, self.context)
        elif choice == "3":
            from greenlight.settings_screens import SettingsScreen
            return ScreenResult(NavigationAction.PUSH, SettingsScreen, self.context)
        elif choice in ["4", "q"]:
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, MainMenuScreen, self.context)
