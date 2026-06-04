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
            self.layout["header"].update(Panel(
                f"🌿 {APP_NAME} v0.1 - Welcome {config.get_op_name(op)}    [yellow]⚠  Shopify scanner paused[/yellow]",
                style="bold green"
            ))
        else:
            self.layout["header"].update(Panel(f"🌿 {APP_NAME} v0.1", style="bold green"))
        return

    def render(self):
        self.console.clear()
        self.console.print(self.layout, end="")

    def read_key(self):
        """Read a single keypress and return a normalized token.

        Returns one of 'UP', 'DOWN', 'LEFT', 'RIGHT', 'ENTER', 'ESC', or the
        literal character typed (letters lowercased). Arrow keys arrive as ANSI
        escape sequences (ESC [ A/B/C/D) and are decoded here so callers get a
        clean token without pressing Enter.

        Falls back to a line read when stdin isn't a TTY (piped input/tests).
        Raises KeyboardInterrupt on Ctrl-C.
        """
        import termios
        import tty

        if not sys.stdin.isatty():
            line = sys.stdin.readline()
            if not line:
                return 'ESC'
            line = line.strip().lower()
            return 'ENTER' if line == '' else line

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            ch = sys.stdin.read(1)
            if ch == '\x03':  # Ctrl-C
                raise KeyboardInterrupt
            if ch in ('\r', '\n'):
                return 'ENTER'
            if ch == '\x1b':
                # Bare ESC, or the start of an arrow-key sequence. Give the
                # trailing bytes a moment to arrive (a real arrow press sends
                # ESC [ X near-instantly, but a remote/Pi terminal can lag) so
                # the whole sequence is consumed in one read and no stray bytes
                # leak into the next keypress.
                if select.select([sys.stdin], [], [], 0.05)[0]:
                    seq = sys.stdin.read(2)
                    return {
                        '[A': 'UP', '[B': 'DOWN',
                        '[C': 'RIGHT', '[D': 'LEFT',
                    }.get(seq, 'ESC')
                return 'ESC'
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def wait_back(self):
        """Block until the user presses 'q' to go back, no Enter required.

        For read-only / info screens that have nothing to do but return. Other
        keys are ignored; Enter is also accepted as a forgiving fallback, but
        footers should advertise 'q' so the back affordance is consistent
        app-wide. Caller is responsible for having already rendered the screen.
        """
        while True:
            key = self.read_key()
            if key in ('q', 'ENTER'):
                return

    def page_size(self, reserved=20, minimum=5):
        """Number of list rows that fit in the body for the current terminal.

        `reserved` covers the fixed layout chrome (margin 1 + header 3 +
        footer 10) plus a table's own header/border rows (~6). Falls back to
        `minimum` rows on very short terminals so a page is never empty.
        """
        height = self.console.size.height
        return max(minimum, height - reserved)

    def paginate(self, items, build_page, *, footer_hint="", page_size=None,
                 actions=None, start_page=0):
        """Page through a long list with n/p/q navigation.

        Runs its own input loop (like render_footer_menu). Reusable across any
        screen that needs to show more rows than fit on screen.

        Args:
            items: full list of items to display.
            build_page(page_items, page_index, total_pages) -> renderable:
                callback returning a Rich renderable (e.g. a Table) for one
                page's slice of items.
            footer_hint: extra text shown alongside the nav keys.
            page_size: rows per page; defaults to what fits the terminal.
            actions: optional dict mapping a single lowercase key char to a
                short footer label (e.g. {'a': 'Assign cable'}). Pressing that
                key stops paging and returns control to the caller.
            start_page: page index to open on (clamped to range). Lets a caller
                that re-enters after an action resume where the user left off.

        Returns:
            None when the user backs out with 'q'. When an action key is
            pressed, a dict {'key', 'page_items', 'page'} describing what was
            pressed and the page in view, so the caller can act on it.
        """
        actions = actions or {}
        if page_size is None:
            page_size = self.page_size()
        total_pages = max(1, (len(items) + page_size - 1) // page_size)
        page = min(max(start_page, 0), total_pages - 1)

        while True:
            start = page * page_size
            page_items = items[start:start + page_size]
            self.layout["body"].update(build_page(page_items, page, total_pages))

            nav = []
            if total_pages > 1:
                nav.append(f"Page [cyan]{page + 1}/{total_pages}[/cyan]")
                if page > 0:
                    nav.append("[green]p.[/green] Prev")
                if page < total_pages - 1:
                    nav.append("[green]n.[/green] Next")
            for k, label in actions.items():
                nav.append(f"[green]{k}.[/green] {label}")
            nav.append("[green]q.[/green] Back")
            if footer_hint:
                nav.append(footer_hint)
            self.layout["footer"].update(Panel("   ".join(nav), title="Options"))
            self.render()

            key = self.read_key()
            if key == "q":
                return None
            elif key in actions:
                return {"key": key, "page_items": page_items, "page": page}
            elif key in ("n", "ENTER") and page < total_pages - 1:
                page += 1
            elif key == "p" and page > 0:
                page -= 1
            # Anything else — including n on the last page, p on the first, and
            # arrow keys — is eaten and just re-renders. Only 'q' or an action
            # key leaves the loop.

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
