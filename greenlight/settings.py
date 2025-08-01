from rich.panel import Panel

class settingsUI:
    def __init__(self, ui_base):
        self.ui = ui_base

    def go(self):
        menu_items = [
            "Option 1",
            "Option 2",
            "Option 2",
            "Exit (q)",
            ]
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, (name) in enumerate(menu_items)
        ]

        self.ui.layout["body"].update(Panel("", title=""))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Settings"))
        while True:
            self.ui.console.print(self.ui.layout)
            choice = self.ui.console.input("Choose: ")
            if choice == "1":
                inventory.init()
            elif choice == "2":
                cable.init()
            elif choice == "3":
                settings.init()
            elif choice in ["4", "q"]:
                return
            else:
                continue
