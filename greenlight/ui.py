from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout

import os
import sys
import select
import time

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
        self.console.print(self.layout, end="")

    def render_footer_menu(self, menu_items, title):
        menu_items.append({"label": "Quit (q)", "action": "quit"})
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

    def get_serial_number_scan_or_manual(self):
        """Get serial number via barcode scanner or manual keyboard input"""
        from greenlight.hardware.barcode_scanner import get_scanner

        scanner = get_scanner()

        # Try to initialize and start scanner
        scanner_available = False
        if scanner.initialize():
            scanner.start_scanning()
            scanner.clear_queue()  # Clear any old scans
            scanner_available = True

        try:
            # Wait for either a scan or keyboard input
            start_time = time.time()
            timeout = 30.0  # 30 second timeout

            while time.time() - start_time < timeout:
                # Check for scanned barcode
                if scanner_available:
                    barcode = scanner.get_scan(timeout=0.1)
                    if barcode:
                        serial_number = barcode.strip().upper()
                        # Show what was scanned by updating the footer
                        self.layout["footer"].update(Panel(
                            f"[bold green]📷 Scanned:[/bold green] {serial_number}",
                            title="Barcode Detected",
                            border_style="green"
                        ))
                        self.render()
                        time.sleep(0.8)  # Brief pause to show what was scanned
                        return serial_number

                # Check for manual keyboard input
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline().strip().upper()
                    if line:
                        if line == 'Q':
                            return None
                        return line

                time.sleep(0.05)  # Small sleep to prevent busy-waiting

            # Timeout - ask for manual entry
            # Update footer to show timeout message instead of printing
            self.layout["footer"].update(Panel(
                "[yellow]⏰ No scan detected - enter manually or 'q' to quit[/yellow]",
                title="Manual Entry"
            ))
            self.render()

            serial_number = self.console.input("Serial number: ").strip().upper()

            if serial_number == 'Q':
                return None

            return serial_number if serial_number else None

        except KeyboardInterrupt:
            return None
        finally:
            if scanner_available:
                scanner.stop_scanning()
