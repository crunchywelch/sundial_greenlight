from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout

import os

from greenlight import config
from greenlight.config import APP_NAME

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


    def header(self, op=""):
        if config.get_op_name(op):
            self.layout["header"].update(Panel(f"🌿 {APP_NAME} v0.1 - Welcome {config.get_op_name(op)}", style="bold green"))
        else:
            self.layout["header"].update(Panel(f"🌿 {APP_NAME} v0.1", style="bold green"))
        return

    def render(self):
        self.console.clear()
        self.console.print(self.layout)





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
