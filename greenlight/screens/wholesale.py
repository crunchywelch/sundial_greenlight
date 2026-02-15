"""
Wholesale batch registration code screen.

Allows operator to scan cables going to wholesale/reseller,
generate registration codes, and print registration labels.
"""

import time
import logging

from rich.panel import Panel
from rich.table import Table

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.db import get_audio_cable, format_serial_number, batch_assign_registration_codes
from greenlight.registration import generate_registration_url

logger = logging.getLogger(__name__)


class WholesaleBatchScreen(Screen):
    """Scan cables for wholesale, generate registration codes, print labels"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        # Batch: list of cable records to process
        batch = []
        batch_serials = set()  # For fast duplicate check

        while True:
            self.ui.console.clear()
            self.ui.header(operator)

            # Build batch table
            if batch:
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("#", style="dim", width=4)
                table.add_column("Serial", style="cyan", width=12)
                table.add_column("SKU", style="green", width=12)
                table.add_column("Cable", width=30)

                for i, cable in enumerate(batch, 1):
                    name = cable.get('series', '')
                    length = cable.get('length', '')
                    if isinstance(length, (int, float)):
                        length = str(int(length)) if length == int(length) else str(length)
                    color = cable.get('color_pattern', '')
                    cable_name = f"{name} {length}' {color}".strip()
                    table.add_row(str(i), cable.get('serial_number', ''), cable.get('sku', ''), cable_name)

                body_content = table
            else:
                body_content = "[dim]No cables scanned yet. Scan a cable barcode to add it to the batch.[/dim]"

            self.ui.layout["body"].update(Panel(
                body_content,
                title=f"Wholesale Batch ({len(batch)} cables)",
                subtitle="Scan cables to add to batch"
            ))

            # Footer with available actions
            footer_parts = [
                "[bold green]Scan barcode[/bold green] to add cable",
            ]
            if batch:
                footer_parts.append("[cyan]'g'[/cyan] = Generate codes + print labels")
            footer_parts.append("[cyan]'q'[/cyan] = Cancel / go back")

            self.ui.layout["footer"].update(Panel(
                " | ".join(footer_parts),
                title="Options", border_style="green"
            ))
            self.ui.render()

            # Get input (scan or command)
            serial_input = self._get_input()

            if not serial_input:
                continue

            input_lower = serial_input.lower()

            if input_lower == 'q':
                return ScreenResult(NavigationAction.POP)

            if input_lower == 'g' and batch:
                # Generate codes and print labels
                return self._generate_and_print(operator, batch)

            # Treat as serial number scan
            formatted_serial = format_serial_number(serial_input)

            # Check for duplicate in current batch
            if formatted_serial in batch_serials:
                self._show_error(operator, f"Cable {formatted_serial} is already in this batch")
                continue

            # Look up cable in database
            cable_record = get_audio_cable(formatted_serial)

            if not cable_record:
                self._show_error(operator, f"Cable {formatted_serial} not found in database")
                continue

            # Check if cable already has a registration code
            if cable_record.get('registration_code'):
                self._show_error(
                    operator,
                    f"Cable {formatted_serial} already has registration code: {cable_record['registration_code']}"
                )
                continue

            # Add to batch
            batch.append(cable_record)
            batch_serials.add(formatted_serial)

    def _get_input(self):
        """Get serial number via barcode scanner or manual keyboard input"""
        from greenlight.hardware.barcode_scanner import get_scanner
        import select
        import sys

        scanner = get_scanner()

        scanner_available = False
        if scanner.initialize():
            scanner.start_scanning()
            scanner.clear_queue()
            scanner_available = True

        try:
            while True:
                if scanner_available:
                    barcode = scanner.get_scan(timeout=0.1)
                    if barcode:
                        return barcode.strip().upper()

                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline().strip().upper()
                    if line:
                        return line

                time.sleep(0.1)
        except KeyboardInterrupt:
            return None
        finally:
            if scanner_available:
                scanner.stop_scanning()

    def _show_error(self, operator, message):
        """Show an error message briefly"""
        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold red]{message}[/bold red]",
            title="Error", style="red"
        ))
        self.ui.layout["footer"].update(Panel("Press Enter to continue", title=""))
        self.ui.render()
        try:
            self.ui.console.input("")
        except KeyboardInterrupt:
            pass

    def _generate_and_print(self, operator, batch):
        """Generate registration codes for the batch and print labels.

        Returns:
            ScreenResult to navigate after completion
        """
        serial_numbers = [c['serial_number'] for c in batch]

        # Show progress
        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"Generating registration codes for {len(serial_numbers)} cables...",
            title="Processing", style="blue"
        ))
        self.ui.layout["footer"].update(Panel("Please wait...", title=""))
        self.ui.render()

        # Generate codes in database
        result = batch_assign_registration_codes(serial_numbers)

        if not result.get('results') and not result.get('success'):
            self._show_error(operator, f"Failed to generate codes: {result.get('message', 'Unknown error')}")
            return ScreenResult(NavigationAction.POP)

        # Print labels for successful codes
        from greenlight.hardware.interfaces import hardware_manager, PrintJob

        label_printer = hardware_manager.get_label_printer()
        printer_available = label_printer and label_printer.is_ready() if label_printer else False

        printed_count = 0
        results_list = result.get('results', [])
        errors_list = result.get('errors', [])

        for i, code_result in enumerate(results_list):
            serial = code_result['serial_number']
            reg_code = code_result['registration_code']

            # Find cable record for SKU
            cable_record = next((c for c in batch if c['serial_number'] == serial), {})
            sku = cable_record.get('sku', '')
            reg_url = generate_registration_url(reg_code)

            # Update progress
            self.ui.layout["body"].update(Panel(
                f"Processing {i + 1}/{len(results_list)}...\n\n"
                f"Serial: {serial}\n"
                f"Code: {reg_code}",
                title="Generating + Printing", style="blue"
            ))
            self.ui.render()

            if printer_available:
                label_data = {
                    'registration_code': reg_code,
                    'registration_url': reg_url,
                    'serial_number': serial,
                    'sku': sku,
                }
                print_job = PrintJob(
                    template="registration_label",
                    data=label_data,
                    quantity=1
                )
                if label_printer.print_labels(print_job):
                    printed_count += 1
                time.sleep(0.3)  # Brief pause between prints

        # Show summary
        self.ui.console.clear()
        self.ui.header(operator)

        summary_table = Table(show_header=True, header_style="bold magenta")
        summary_table.add_column("Serial", style="cyan", width=12)
        summary_table.add_column("Registration Code", style="bold green", width=12)
        summary_table.add_column("SKU", style="dim", width=12)

        for code_result in results_list:
            serial = code_result['serial_number']
            reg_code = code_result['registration_code']
            cable_record = next((c for c in batch if c['serial_number'] == serial), {})
            sku = cable_record.get('sku', '')
            summary_table.add_row(serial, reg_code, sku)

        # Add errors if any
        error_text = ""
        if errors_list:
            error_text = "\n\n[bold red]Errors:[/bold red]\n"
            for err in errors_list:
                error_text += f"  {err['serial_number']}: {err['error']}\n"

        print_status = ""
        if printer_available:
            print_status = f"\nLabels printed: {printed_count}/{len(results_list)}"
        else:
            print_status = "\n[yellow]Printer not available - no labels printed[/yellow]"

        self.ui.layout["body"].update(Panel(
            summary_table,
            title=f"Wholesale Batch Complete - {len(results_list)} codes generated",
            subtitle=f"{print_status}{error_text}",
            style="green"
        ))
        self.ui.layout["footer"].update(Panel(
            "Press Enter to go back",
            title=""
        ))
        self.ui.render()

        try:
            self.ui.console.input("")
        except KeyboardInterrupt:
            pass

        return ScreenResult(NavigationAction.POP)
