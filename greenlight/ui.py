from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout

import os

from greenlight import config
from greenlight.config import OPERATORS

console = Console()

layout = Layout()
layout.split_column(
    Layout(name="margin", size=1),
    Layout(name="header", size=3),
    Layout(name="body", ratio=2),
)

def init(op=""):
    clear()
    layout["margin"].update(Panel(" "))
    if config.get_op_name(op):
        layout["header"].update(Panel("🌿 Greenlight QC Terminal v0.1 - Welcome "+ config.get_op_name(op), style="bold green"))
    else:
        layout["header"].update(Panel("🌿 Greenlight QC Terminal v0.1", style="bold green"))
    return

def clear():
    console.clear()

def splash():
    init()
    splash_path = os.path.join(os.path.dirname(__file__), "art", "splash.txt")
    with open(splash_path, "r") as f:
        splash_text = f.read()
    console.print(Panel(splash_text, style="bold green", subtitle="Cable QC + Inventory Terminal"))
    input("Press enter to begin...");
    return

def operator_menu():
    rows = [
        f"[green]{i + 1}.[/green] {name} ({code})"
        for i, (code, name) in enumerate(OPERATORS.items())
    ]
    body = "\n".join(rows)
    layout["body"].update(Panel("Please identify yourself to begin"))
    layout["footer"].update(Panel("\n".join(rows), title="Who are you: "))
    console.print(layout)

    codes = list(OPERATORS.keys())
    valid_choices = [str(i + 1) for i in range(len(codes))]
    valid_choices.append("q")
    choice_str = ",".join(valid_choices)
    while True:
        choice = console.input("Choose operator: ("+ choice_str +") ")
        if choice in valid_choices:
            if choice == "q":
                return choice
            else:
                return codes[int(choice) - 1]
        else:
            console.print(layout)
            continue;

def main_menu():
    rows = [
        "[green]1. Inventory Management[/green]",
        "[green]2. Cable QC[/green]",
        "[green]3. Settings[/green]",
        "[green]4. Exit[/green]"
        ]
    layout["body"].update(Panel("", title=""))
    layout["footer"].update(Panel("\n".join(rows), title="Available Operations"))
    while True:
        console.print(layout)
        choice = console.input("Choose: ")
        if choice == "1":
            inventory.init()
        elif choice == "2":
            cable.init()
        elif choice == "3":
            settings.init()
        elif choice == "4":
            return
        else:
            continue
