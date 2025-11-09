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
            title="Scanning", border_style="cyan"
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

            # Check if evdev scanner is available
            from greenlight.hardware.barcode_scanner import get_scanner
            scanner = get_scanner()
            scanner_available = scanner.is_connected() or scanner.initialize()

            if scanner_available:
                self.ui.layout["footer"].update(Panel(
                    "🔍 [bold green]Ready - Scan barcode now[/bold green]\n"
                    "[bright_black]Barcode scanner active - scan label or type manually[/bright_black]\n"
                    "Type 'q' and press Enter to finish",
                    title="Scanner Active", border_style="green"
                ))
            else:
                self.ui.layout["footer"].update(Panel(
                    "⚠️  [yellow]Scanner not detected - manual entry mode[/yellow]\n"
                    "Enter serial number (or 'q' to finish)",
                    title="Manual Entry Mode", style="yellow"
                ))

            self.ui.render()

            # Get serial number via evdev scanner or manual entry
            serial_number = self.get_serial_number_scan_or_manual()

            # Check for quit
            if not serial_number or serial_number.lower() == 'q':
                break

            # Format the serial number (pad to 6 digits)
            from greenlight.db import format_serial_number
            formatted_serial = format_serial_number(serial_number)

            # Show confirmation screen with scanned serial number
            serial_display = f"[bold yellow]{formatted_serial}[/bold yellow]"
            if formatted_serial != serial_number:
                serial_display += f"\n[bright_black](formatted from: {serial_number})[/bright_black]"

            self.ui.layout["body"].update(Panel(
                f"[bold cyan]Scanned Serial Number:[/bold cyan]\n\n"
                f"{serial_display}\n\n"
                f"Cable Type: {cable_type.name()}\n"
                f"SKU: {cable_type.sku}",
                title="📋 Confirm Serial Number",
                border_style="cyan"
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

            # Register the cable in database (note: formatted_serial is already formatted in register_scanned_cable)
            result = register_scanned_cable(serial_number, cable_type.sku, operator)

            if result.get('success'):
                # Successfully registered or updated
                scanned_count += 1
                saved_serial = result['serial_number']  # Use the formatted serial from database
                scanned_serials.append(saved_serial)

                # Show success message (different for update vs new)
                if result.get('updated'):
                    success_msg = f"🔄 Updated in database: {saved_serial}"
                else:
                    success_msg = f"✅ Saved to database: {saved_serial}"

                self.ui.layout["footer"].update(Panel(
                    success_msg,
                    title="Success", style="green"
                ))
                self.ui.render()
                time.sleep(0.8)  # Brief pause to show success
            else:
                # Error registering
                error_type = result.get('error', 'unknown')
                error_msg = result.get('message', 'Unknown error')

                if error_type == 'duplicate':
                    # Show existing record and ask if user wants to update
                    existing = result.get('existing_record', {})
                    user_choice = self.show_duplicate_prompt(operator, cable_type, existing)

                    if user_choice == 'quit':
                        # User wants to quit scanning
                        break
                    elif user_choice == 'update':
                        # User chose to update - retry with update flag
                        update_result = register_scanned_cable(serial_number, cable_type.sku, operator, update_if_exists=True)
                        if update_result.get('success'):
                            scanned_count += 1
                            saved_serial = update_result['serial_number']
                            scanned_serials.append(saved_serial)

                            self.ui.layout["footer"].update(Panel(
                                f"🔄 Updated in database: {saved_serial}",
                                title="Success", style="green"
                            ))
                            self.ui.render()
                            time.sleep(0.8)
                    # else: user chose 'skip', just continue to next scan
                    continue
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

    def show_duplicate_prompt(self, operator, cable_type, existing_record):
        """Show duplicate record prompt and ask if user wants to update it

        Returns:
            'update' - User wants to update the record
            'skip' - User wants to skip this record
            'quit' - User wants to quit scanning
        """
        existing_serial = existing_record.get('serial_number', 'Unknown')
        existing_sku = existing_record.get('sku', 'Unknown')
        existing_operator = existing_record.get('operator', 'Unknown')
        existing_timestamp = existing_record.get('timestamp', 'Unknown')
        existing_notes = existing_record.get('notes', '')

        # Format timestamp
        if hasattr(existing_timestamp, 'strftime'):
            timestamp_str = existing_timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = str(existing_timestamp)

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"⚠️  [bold yellow]Duplicate Serial Number Found[/bold yellow]\n\n"
            f"[bold]Existing Record:[/bold]\n"
            f"  Serial: {existing_serial}\n"
            f"  SKU: {existing_sku}\n"
            f"  Operator: {existing_operator}\n"
            f"  Registered: {timestamp_str}\n"
            f"  Notes: {existing_notes}\n\n"
            f"[bold]New Cable Type:[/bold]\n"
            f"  SKU: {cable_type.sku}\n"
            f"  Name: {cable_type.name()}\n\n"
            f"Do you want to update this record with the new cable type?",
            title="⚠️  Duplicate Serial Number",
            border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "[green]y[/green] = Update record | [red]n[/red] = Skip | [yellow]q[/yellow] = Quit scanning",
            title="Update Record?"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Update? (y/n/q): ").strip().lower()
            if choice == 'q':
                return 'quit'
            elif choice == 'y' or choice == 'yes':
                return 'update'
            else:
                return 'skip'
        except KeyboardInterrupt:
            return 'quit'

    def get_serial_number_scan_or_manual(self):
        """Get serial number via barcode scanner using evdev or manual keyboard input"""
        from greenlight.hardware.barcode_scanner import get_scanner
        import select
        import sys

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
                        # Show what was scanned
                        self.ui.console.print(f"\n[bold green]📷 Scanned:[/bold green] {serial_number}")
                        time.sleep(0.5)  # Brief pause to show what was scanned
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
            self.ui.console.print("\n[yellow]⏰ No scan detected - enter manually or 'q' to quit[/yellow]")
            self.ui.console.print("[bold cyan]►[/bold cyan] ", end="")
            serial_number = self.ui.console.input().strip().upper()

            if serial_number == 'Q':
                return None

            return serial_number if serial_number else None

        except KeyboardInterrupt:
            return None
        finally:
            if scanner_available:
                scanner.stop_scanning()

    def get_serial_number_manual_only(self):
        """Get serial number via manual keyboard entry"""
        try:
            serial_number = self.ui.console.input("Serial number: ").strip().upper()
            return serial_number if serial_number and serial_number.lower() != 'q' else None
        except KeyboardInterrupt:
            return None

    def show_intake_summary(self, operator, cable_type, scanned_count, scanned_serials):
        """Show summary of intake session"""

        # If no cables were scanned, go back to main menu directly
        if scanned_count == 0:
            return ScreenResult(NavigationAction.POP, pop_count=3)

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
        # After showing summary, go back to main menu
        return ScreenResult(NavigationAction.POP, pop_count=2)
