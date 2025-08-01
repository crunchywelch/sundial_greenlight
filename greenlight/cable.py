from rich.panel import Panel

class settingsUI:
    def __init__(self, ui_base):
        self.ui = ui_base

    def go(self):
        rows = [
            "[green]1. Option 1[/green]",
            "[green]2. Option 2[/green]",
            "[green]3. Option 3[/green]",
            "[green]4. Exit (q)[/green]"
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
