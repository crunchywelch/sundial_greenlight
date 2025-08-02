from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout

import os

from greenlight import config
from greenlight.cable import cableUI
from greenlight.inventory import inventoryUI
from greenlight.settings import settingsUI
from greenlight.config import OPERATORS

class UIBase:
    def __init__(self):
        self.console = Console()

        self.layout = Layout()
        self.layout.split_column(
            Layout(name="margin", size=1),
            Layout(name="header", size=3),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=10),
        )

        self.cable_ui = cableUI(self)
        self.inventory_ui = inventoryUI(self)
        self.settings_ui = settingsUI(self)

    def header(self, op=""):
        if config.get_op_name(op):
            self.layout["header"].update(Panel("🌿 Greenlight QC Terminal v0.1 - Welcome "+ config.get_op_name(op), style="bold green"))
        else:
            self.layout["header"].update(Panel("🌿 Greenlight QC Terminal v0.1", style="bold green"))
        return

    def render(self):
        self.console.clear()
        self.console.print(self.layout)

    def splash(self):
        self.console.clear()
        self.header()
        splash_path = os.path.join(os.path.dirname(__file__), "art", "splash.txt")
        with open(splash_path, "r") as f:
            splash_text = f.read()
        self.console.print(Panel(splash_text, style="bold green", subtitle="Cable QC + Inventory Terminal"))
        self.console.input("Press enter to begin...");
        return

    def operator_menu(self):
        rows = [
            f"[green]{i + 1}.[/green] {name} ({code})"
            for i, (code, name) in enumerate(OPERATORS.items())
        ]

        self.header()
        self.layout["body"].update(Panel("Please identify yourself to begin"))
        self.layout["footer"].update(Panel("\n".join(rows), title="Who are you?"))
        self.render()

        codes = list(OPERATORS.keys())
        valid_choices = [str(i + 1) for i in range(len(codes))]
        valid_choices.append("q")
        choice_str = ",".join(valid_choices)
        while True:
            choice = self.console.input("Choose operator: ("+ choice_str +") ")
            if choice in valid_choices:
                if choice == "q":
                    return choice
                else:
                    return codes[int(choice) - 1]
            else:
                self.render()
                continue;

    def render_main_menu(self, op):
        menu_items = [
            "Audio Cable QC",
            "Inventory Management",
            "Settings",
            "Exit (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, (name) in enumerate(menu_items)
        ]

        self.header(op)
        self.layout["body"].update(Panel("", title=""))
        self.layout["footer"].update(Panel("\n".join(rows), title="Available Operations"))
        self.render()

    def main_menu(self, op):
        self.render_main_menu(op)
        while True:
            choice = self.console.input("Choose: ")
            if choice == "1":
                self.cable_ui.go()
                self.render_main_menu(op)
            elif choice == "2":
                self.inventory_ui.go()
                self.render_main_menu(op)
            elif choice == "3":
                self.settings_ui.go()
                self.render_main_menu(op)
            elif choice in ["4", "q"]:
                return
            else:
                continue


    def render_footer_menu(self, menu_items, title):
        menu_items.append({"label": "Exit (q)", "action": "quit"})
        rows = [
            f"[green]{i + 1}.[/green] {item['label']}"
            for i, item in enumerate(menu_items)
        ]

        self.layout["footer"].update(Panel("\n".join(rows), title=title))
        self.render()

        while True:
            choice = self.console.input("Choose: ")
            if choice == "q":
                return
            try:
                num = int(choice) - 1
                if callable(menu_items[num]["action"]):
                    return num
                elif menu_items[num]["action"] == "quit":
                    return
            except:
                self.render()
                continue
