from rich.panel import Panel
from rich.table import Table
from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import APP_NAME
from greenlight.hardware.interfaces import hardware_manager
import time

# Note: CableTestScreen is imported at runtime to avoid circular imports


class TestAssembledCableScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "🔍 Test Assembled Cable\n\n"
            "Scan the barcode on the cable label or manually enter the serial number\n"
            "to look up cable information and run tests.",
            title="Test Assembled Cable"
        ))
        
        # Check if scanner is available
        scanner_available = hardware_manager.scanner and hardware_manager.scanner.is_connected()
        
        if scanner_available:
            self.ui.layout["footer"].update(Panel(
                "Scan barcode or press 'm' for manual entry | Back (q)",
                title="Input Method"
            ))
        else:
            self.ui.layout["footer"].update(Panel(
                "Enter serial number (SD######) | Back (q)",
                title="Serial Number"
            ))
        
        self.ui.render()
        
        # Try barcode scanning first if available
        if scanner_available:
            serial_number = self.get_serial_number_with_scanner()
        else:
            serial_number = self.get_serial_number_manual()
        
        if not serial_number:
            return ScreenResult(NavigationAction.POP)
        
        # Look up cable record
        return self.lookup_and_test_cable(operator, serial_number)
    
    def get_serial_number_with_scanner(self):
        """Get serial number via barcode scanner or manual entry"""
        import time
        import sys
        import select
        
        self.ui.layout["footer"].update(Panel(
            "🔍 Ready to scan barcode... (press 'm' for manual entry, 'q' to quit)",
            title="Scanning", style="blue"
        ))
        self.ui.render()
        
        # Wait for scan or manual input
        start_time = time.time()
        timeout = 10.0  # 10 second timeout
        
        while time.time() - start_time < timeout:
            # Check for keyboard input (manual mode)
            if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                key = sys.stdin.read(1).lower()
                if key == 'q':
                    return None
                elif key == 'm':
                    return self.get_serial_number_manual()
            
            # Try barcode scan
            scan_result = hardware_manager.scanner.scan(timeout=0.5)
            if scan_result and scan_result.success:
                serial_number = scan_result.data.strip().upper()
                self.ui.layout["footer"].update(Panel(
                    f"✅ Scanned: {serial_number}",
                    title="Scan Complete", style="green"
                ))
                self.ui.render()
                time.sleep(1)  # Brief pause to show result
                return serial_number
            
            time.sleep(0.1)  # Brief pause between scan attempts
        
        # Timeout - fallback to manual entry
        self.ui.layout["footer"].update(Panel(
            "⏰ Scan timeout - switching to manual entry",
            title="Timeout", style="yellow"
        ))
        self.ui.render()
        time.sleep(1)
        return self.get_serial_number_manual()
    
    def get_serial_number_manual(self):
        """Get serial number via manual keyboard entry"""
        self.ui.layout["footer"].update(Panel(
            "Enter serial number (SD######):",
            title="Manual Entry"
        ))
        self.ui.render()
        
        try:
            serial_number = self.ui.console.input("Serial number: ").strip().upper()
            return serial_number if serial_number else None
        except KeyboardInterrupt:
            return None
    
    def lookup_and_test_cable(self, operator, serial_number):
        """Look up cable by serial number and start testing"""
        from greenlight.db import get_audio_cable
        from greenlight.cable import CableType
        
        # Check if serial number exists
        cable_record = get_audio_cable(serial_number)
        
        if not cable_record:
            self.ui.layout["body"].update(Panel(
                f"❌ Serial number not found: {serial_number}\n\n"
                f"This serial number may not exist or has not been generated yet.\n"
                f"Check the label and try again.",
                title="Serial Number Not Found", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.REPLACE, TestAssembledCableScreen, self.context)
        
        # Check if already tested
        if cable_record.get('resistance_ohms') is not None:
            return self.show_existing_test_results(operator, serial_number, cable_record)
        
        # Load cable type for testing
        try:
            from greenlight.cable_screens import CableTestScreen
            cable_type = CableType()
            cable_type.load(cable_record['sku'])

            # Show cable info and start testing
            new_context = self.context.copy()
            new_context['cable_type'] = cable_type
            new_context['serial_number'] = serial_number
            new_context['testing_mode'] = 'assembled'  # Flag to indicate this is testing assembled cable

            return ScreenResult(NavigationAction.PUSH, CableTestScreen, new_context)
            
        except ValueError as e:
            self.ui.layout["body"].update(Panel(
                f"❌ Error loading cable type: {str(e)}\n\n"
                f"Serial: {serial_number}\n"
                f"SKU: {cable_record.get('sku', 'Unknown')}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
    
    def show_existing_test_results(self, operator, serial_number, cable_record):
        """Display results for already tested cable"""
        resistance = cable_record.get('resistance_ohms', 'N/A')
        capacitance = cable_record.get('capacitance_pf', 'N/A')
        test_operator = cable_record.get('operator', 'Unknown')
        arduino_unit = cable_record.get('arduino_unit_id', 'Unknown')
        test_time = cable_record.get('test_timestamp', 'Unknown')
        
        if hasattr(test_time, 'strftime'):
            timestamp_str = test_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = str(test_time)
        
        self.ui.layout["body"].update(Panel(
            f"📋 Cable Already Tested\n\n"
            f"Serial: {serial_number}\n"
            f"SKU: {cable_record.get('sku', 'Unknown')}\n"
            f"Name: {cable_record.get('series', '')} {cable_record.get('length', '')}ft {cable_record.get('color_pattern', '')}\n\n"
            f"Test Results:\n"
            f"• Resistance: {resistance} Ω\n"
            f"• Capacitance: {capacitance} pF\n"
            f"• Tested by: {test_operator}\n"
            f"• Arduino Unit: #{arduino_unit}\n"
            f"• Test Time: {timestamp_str}",
            title="Test Results", style="green"
        ))
        self.ui.layout["footer"].update(Panel("Press 'r' to retest, Enter to continue", title=""))
        self.ui.render()
        
        choice = self.ui.console.input("Action: ").lower()
        if choice == 'r':
            # Allow retesting - load cable type and start test
            try:
                from greenlight.cable_screens import CableTestScreen
                cable_type = CableType()
                cable_type.load(cable_record['sku'])

                new_context = self.context.copy()
                new_context['cable_type'] = cable_type
                new_context['serial_number'] = serial_number
                new_context['testing_mode'] = 'retest'

                return ScreenResult(NavigationAction.PUSH, CableTestScreen, new_context)
            except ValueError as e:
                return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.POP)


class ScanCableIntakeScreen(Screen):
    """Screen for scanning cables and registering them in the database"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")

        if not cable_type or not cable_type.is_loaded():
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No cable type selected", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        # Show scanning interface
        return self.scan_cables_loop(operator, cable_type)

    def scan_cables_loop(self, operator, cable_type):
        """Main scanning loop for registering multiple cables"""
        from greenlight.db import register_scanned_cable

        scanned_count = 0
        scanned_serials = []

        while True:
            # Show current status
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan", width=20)
            table.add_column("Value", style="green")

            table.add_row("Cable Type", cable_type.name())
            table.add_row("SKU", cable_type.sku)
            table.add_row("Scanned Count", str(scanned_count))
            if scanned_serials:
                recent_serials = scanned_serials[-5:]  # Show last 5
                table.add_row("Recent Scans", "\n".join(recent_serials))

            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                table,
                title="📦 Register Cables - Scan Labels",
                subtitle="Scan barcode labels to register cables in database"
            ))

            # Check if scanner is available
            scanner_available = hardware_manager.scanner and hardware_manager.scanner.is_connected()

            if scanner_available:
                self.ui.layout["footer"].update(Panel(
                    "🔍 [bold green]Ready - Scan barcode now[/bold green]\n"
                    "[dim]Scanner will type serial number automatically[/dim]\n"
                    "Type 'q' and press Enter to finish",
                    title="Scanner Active", style="blue"
                ))
            else:
                self.ui.layout["footer"].update(Panel(
                    "Enter serial number (or 'q' to finish)",
                    title="Manual Entry Mode", style="yellow"
                ))

            self.ui.render()

            # Get serial number via scanner or manual entry
            # Note: Scanner acts as keyboard, so both paths use the same method
            serial_number = self.get_serial_number_scan_or_manual()

            # Check for quit
            if not serial_number or serial_number.lower() == 'q':
                break

            # Show confirmation screen with scanned serial number
            self.ui.layout["body"].update(Panel(
                f"[bold cyan]Scanned Serial Number:[/bold cyan]\n\n"
                f"[bold yellow]{serial_number}[/bold yellow]\n\n"
                f"Cable Type: {cable_type.name()}\n"
                f"SKU: {cable_type.sku}",
                title="📋 Confirm Serial Number",
                style="blue"
            ))
            self.ui.layout["footer"].update(Panel(
                "Press [green]Enter[/green] to save | 'n' to skip | 'q' to quit",
                title="Confirm"
            ))
            self.ui.render()

            # Wait for confirmation
            try:
                confirmation = self.ui.console.input("").strip().lower()
            except KeyboardInterrupt:
                break

            # Handle confirmation response
            if confirmation == 'q':
                break
            elif confirmation == 'n':
                # Skip this serial number
                self.ui.layout["footer"].update(Panel(
                    f"⏭️  Skipped: {serial_number}",
                    title="Skipped", style="yellow"
                ))
                self.ui.render()
                time.sleep(0.8)
                continue
            # Empty string (Enter pressed) or anything else means confirm

            # Register the cable in database
            result = register_scanned_cable(serial_number, cable_type.sku)

            if result.get('success'):
                # Successfully registered
                scanned_count += 1
                scanned_serials.append(serial_number)

                # Show brief success message
                self.ui.layout["footer"].update(Panel(
                    f"✅ Saved to database: {serial_number}",
                    title="Success", style="green"
                ))
                self.ui.render()
                time.sleep(0.8)  # Brief pause to show success
            else:
                # Error registering
                error_type = result.get('error', 'unknown')
                error_msg = result.get('message', 'Unknown error')

                if error_type == 'duplicate':
                    error_display = f"⚠️  Duplicate: {serial_number}\n\nThis serial number is already in the database."
                    error_style = "yellow"
                else:
                    error_display = f"❌ Error: {error_msg}"
                    error_style = "red"

                self.ui.layout["footer"].update(Panel(
                    error_display,
                    title="Registration Error", style=error_style
                ))
                self.ui.render()
                time.sleep(1.5)  # Longer pause for errors

        # Show final summary
        return self.show_intake_summary(operator, cable_type, scanned_count, scanned_serials)

    def get_serial_number_scan_or_manual(self):
        """Get serial number via scanner - Zebra DS2208 sends as keyboard input"""
        # Zebra DS2208 scanner appears as USB HID keyboard
        # When a barcode is scanned, it types the characters and presses Enter
        # Rich's console.input() will capture this naturally

        try:
            # This will capture both scanner input and manual keyboard input
            # The scanner types the serial number and presses Enter automatically
            # Show a visible prompt so user knows where the input will appear
            self.ui.console.print("\n[bold cyan]►[/bold cyan] ", end="")
            serial_number = self.ui.console.input().strip().upper()

            # Check if user wants to quit
            if serial_number.lower() == 'q':
                return None

            return serial_number if serial_number else None

        except KeyboardInterrupt:
            return None

    def get_serial_number_manual_only(self):
        """Get serial number via manual keyboard entry"""
        try:
            serial_number = self.ui.console.input("Serial number: ").strip().upper()
            return serial_number if serial_number and serial_number.lower() != 'q' else None
        except KeyboardInterrupt:
            return None

    def show_intake_summary(self, operator, cable_type, scanned_count, scanned_serials):
        """Show summary of intake session"""

        summary_table = Table(show_header=True, header_style="bold magenta")
        summary_table.add_column("Metric", style="cyan", width=25)
        summary_table.add_column("Value", style="green")

        summary_table.add_row("Cable Type", cable_type.name())
        summary_table.add_row("SKU", cable_type.sku)
        summary_table.add_row("Total Scanned", str(scanned_count))
        summary_table.add_row("Operator", operator)

        if scanned_serials:
            summary_table.add_row("Serial Range", f"{scanned_serials[0]} to {scanned_serials[-1]}")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            summary_table,
            title="✅ Cable Registration Complete",
            style="green"
        ))
        self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
        self.ui.render()

        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)