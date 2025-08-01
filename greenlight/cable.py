from rich.panel import Panel

class cableUI:
    def __init__(self, ui_base):
        self.ui = ui_base

    def go(self):
        menu_items = [
            "Select Cable Type",
            "Run Test",
            "Print Cable Tag",
            "Print Cable Wrap",
            "Exit (q)",
            ]
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, (name) in enumerate(menu_items)
        ]

        self.ui.layout["body"].update(Panel("", title=""))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Audio Cable QC"))
        while True:
            self.ui.console.print(self.ui.layout)
            choice = self.ui.console.input("Choose: ")
            if choice == "1":
                self.select_cable()
            elif choice == "2":
                cable.()
            elif choice == "3":
                settings.init()
            elif choice in ["4", "q"]:
                return
            else:
                continue
