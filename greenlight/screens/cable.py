from rich.panel import Panel
import logging

logger = logging.getLogger(__name__)
import sys
import termios
import tty

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import APP_NAME, EXIT_MESSAGE
from greenlight.cable import (
    CableType, get_all_skus, filter_skus, get_distinct_series, 
    get_distinct_color_patterns, get_distinct_lengths, get_distinct_connector_types,
    find_cable_by_attributes
)
from greenlight.testing import MockArduinoTester, ArduinoATmega32Tester
from greenlight.config import USE_REAL_ARDUINO, ARDUINO_PORT, ARDUINO_BAUDRATE
from greenlight.db import insert_audio_cable, get_audio_cable, register_scanned_cable, format_serial_number, update_cable_test_results
from rich.table import Table
import time


class CableQCScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        # Cable management menu
        menu_items = [
            "Scan Cables",
            "Register Cables",
            "Test Cables",
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "Audio Cable Management\n\n"
            "• Scan Cables - Scan cable label to view information and customer\n"
            "• Register Cables - Scan cable labels to register or view cable information\n"
            "• Test Cables - Scan serial number from assembled cable and run QC tests",
            title="Cable Management Options"
        ))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Audio Cable Management"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")

        # Debug logging
        with open("/tmp/greenlight_debug.log", "a") as f:
            f.write(f"CableQCScreen: User chose option '{choice}'\n")

        if choice == "1":  # Scan Cables
            with open("/tmp/greenlight_debug.log", "a") as f:
                f.write(f"CableQCScreen: Pushing ScanCableLookupScreen (class: {ScanCableLookupScreen})\n")
            return ScreenResult(NavigationAction.PUSH, ScanCableLookupScreen, self.context)
        elif choice == "2":  # Register Cables
            new_context = self.context.copy()
            new_context["selection_mode"] = "intake"
            return ScreenResult(NavigationAction.PUSH, CableSelectionForIntakeScreen, new_context)
        elif choice == "3":  # Test Cables
            return ScreenResult(NavigationAction.PUSH, TestAssembledCableScreen, self.context)
        elif choice == "4" or choice.lower() == "q":  # Back
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, CableQCScreen, self.context)


class ScanCableLookupScreen(Screen):
    """Simple cable lookup screen - scan and view cable info"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        # Debug log
        with open("/tmp/greenlight_debug.log", "a") as f:
            f.write(f"ScanCableLookupScreen.run() called for operator: {operator}\n")

        # Initial body content
        body_panel = Panel(
            "🔍 Scan Cable Lookup\n\n"
            "Scan a cable barcode to view its information, test results, and customer assignment.\n\n"
            "Or use menu options below to register new cables.\n\n"
            "Ready to scan...",
            title="Scan Cables"
        )

        while True:
            # Update display with current body content (don't clear console)
            self.ui.header(operator)
            self.ui.layout["body"].update(body_panel)
            self.ui.layout["footer"].update(Panel(
                "🔍 [bold green]Scan barcode now[/bold green] | [cyan]'r'[/cyan] = Register Cables | [cyan]'q'[/cyan] = Back",
                title="Options", border_style="green"
            ))
            self.ui.render()

            # Debug log
            with open("/tmp/greenlight_debug.log", "a") as f:
                f.write("About to call get_serial_number_scan_or_manual()\n")

            # Get serial number or menu command
            serial_number = self.get_serial_number_scan_or_manual()

            # Debug log
            with open("/tmp/greenlight_debug.log", "a") as f:
                f.write(f"Got input: {serial_number}\n")

            # Check for menu commands
            if not serial_number:
                continue

            input_lower = serial_number.lower()

            if input_lower == 'q':
                return ScreenResult(NavigationAction.POP)
            elif input_lower == 'r':
                # Go to attribute selection for registration
                new_context = self.context.copy()
                new_context["selection_mode"] = "intake"
                return ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, new_context)

            # Otherwise treat as serial number lookup
            # Format serial number
            from greenlight.db import format_serial_number
            formatted_serial = format_serial_number(serial_number)

            # Look up cable in database
            from greenlight.db import get_audio_cable
            cable_record = get_audio_cable(formatted_serial)

            # Clear console to refresh with new info
            self.ui.console.clear()

            if cable_record:
                # Show cable info and handle user actions
                action_result = self.show_cable_info_with_actions(operator, cable_record)
                if action_result:
                    return action_result
                # If no action result, continue scanning (user pressed enter)
                body_panel = Panel(
                    "🔍 Scan Cable Lookup\n\n"
                    "Ready to scan next cable...",
                    title="Scan Cables"
                )
            else:
                # Get not found panel and keep it displayed
                body_panel = self.show_not_found(operator, formatted_serial)

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
            logger.info(f"Scanner initialized: {scanner.device_name}")
        else:
            logger.warning("Scanner failed to initialize")

        try:
            # Wait indefinitely for either a scan or keyboard input
            # No timeout - user must explicitly quit with 'q'
            logger.info("Waiting for scan or manual input...")

            while True:
                # Check for scanned barcode
                if scanner_available:
                    barcode = scanner.get_scan(timeout=0.1)
                    if barcode:
                        serial_number = barcode.strip().upper()
                        logger.info(f"Scanned barcode: {serial_number}")
                        return serial_number

                # Check for manual keyboard input
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline().strip().upper()
                    if line:
                        logger.info(f"Manual input: {line}")
                        return line

                time.sleep(0.1)  # Small sleep to prevent busy-waiting

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt during scan")
            return None
        except Exception as e:
            logger.error(f"Error during scan: {e}")
            return None
        finally:
            if scanner_available:
                scanner.stop_scanning()

    def show_cable_info_with_actions(self, operator, cable_record):
        """Display cable info and prompt for action (assign or continue)

        Returns:
            ScreenResult if user wants to assign to customer, None to continue scanning
        """
        # Display cable info
        cable_info_panel = self.build_cable_info_panel(cable_record)

        self.ui.header(operator)
        self.ui.layout["body"].update(cable_info_panel)

        # Check if cable is already assigned
        customer_gid = cable_record.get("shopify_gid")
        if customer_gid:
            footer_text = "[cyan]Press Enter to continue scanning[/cyan]"
        else:
            footer_text = "[cyan]'a'[/cyan] = Assign to customer | [cyan]Enter[/cyan] = Continue scanning"

        self.ui.layout["footer"].update(Panel(footer_text, title="Options"))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()

            if choice == 'a' and not customer_gid:
                # Push customer lookup screen with cable serial in context
                from greenlight.screens.orders import CustomerLookupScreen
                new_context = self.context.copy()
                new_context["assign_cable_serial"] = cable_record['serial_number']
                new_context["assign_cable_sku"] = cable_record['sku']
                return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, new_context)

            # Otherwise continue scanning
            return None

        except KeyboardInterrupt:
            return None

    def build_cable_info_panel(self, cable_record):
        """Build the cable information panel (extracted for reuse)"""
        serial_number = cable_record.get("serial_number", "N/A")
        sku = cable_record.get("sku", "N/A")
        series = cable_record.get("series", "N/A")
        length = cable_record.get("length", "N/A")
        color_pattern = cable_record.get("color_pattern", "N/A")
        connector_type = cable_record.get("connector_type", "N/A")
        resistance_ohms = cable_record.get("resistance_ohms")
        capacitance_pf = cable_record.get("capacitance_pf")
        cable_operator = cable_record.get("operator", "N/A")
        test_timestamp = cable_record.get("test_timestamp")
        updated_timestamp = cable_record.get("updated_timestamp")

        # Format test results
        if resistance_ohms is not None:
            resistance_str = f"{resistance_ohms:.2f} Ω"
            test_status = "✅ Tested"
        else:
            resistance_str = "Not tested"
            test_status = "⏳ Not tested"

        if capacitance_pf is not None:
            capacitance_str = f"{capacitance_pf:.2f} pF"
        else:
            capacitance_str = "Not tested"

        # Format timestamps
        if test_timestamp:
            if hasattr(test_timestamp, 'strftime'):
                test_timestamp_str = test_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                test_timestamp_str = str(test_timestamp)
        else:
            test_timestamp_str = "Not tested"

        if updated_timestamp:
            if hasattr(updated_timestamp, 'strftime'):
                updated_timestamp_str = updated_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                updated_timestamp_str = str(updated_timestamp)
        else:
            updated_timestamp_str = "N/A"

        # Build cable info display
        cable_info = f"""[bold yellow]Serial Number:[/bold yellow] {serial_number}
[bold yellow]SKU:[/bold yellow] {sku}
[bold yellow]Registered:[/bold yellow] {updated_timestamp_str}

[bold cyan]Cable Details:[/bold cyan]
  Series: {series}
  Length: {length} ft
  Color: {color_pattern}
  Connector: {connector_type}"""

        # Add description for MISC cables
        description = cable_record.get("description")
        if sku.endswith("-MISC") and description:
            cable_info += f"\n  Description: {description}"

        cable_info += f"""

[bold green]Test Status:[/bold green] {test_status}
  Resistance: {resistance_str}
  Capacitance: {capacitance_str}
  Tested: {test_timestamp_str}
  Test Operator: {cable_operator if test_timestamp else 'N/A'}"""

        # Check if cable is assigned to a customer
        customer_gid = cable_record.get("shopify_gid")

        if customer_gid:
            # Cable is assigned - fetch customer details
            from greenlight import shopify_client
            customer_numeric_id = customer_gid.split('/')[-1]
            customer = shopify_client.get_customer_by_id(customer_numeric_id)

            if customer:
                customer_name = customer.get("displayName") or "N/A"
                customer_email = customer.get("email") or "N/A"
                customer_phone = customer.get("phone")
                address = customer.get("defaultAddress")
                if not customer_phone and address:
                    customer_phone = address.get("phone")
                customer_phone = customer_phone or "N/A"

                cable_info += f"""

[bold magenta]✅ Assigned To Customer:[/bold magenta]
  Name: {customer_name}
  Email: {customer_email}
  Phone: {customer_phone}"""
            else:
                cable_info += f"""

[bold magenta]Assigned To:[/bold magenta]
  [yellow]Customer ID: {customer_gid}[/yellow]
  [dim](Details not available)[/dim]"""
        else:
            cable_info += """

[bold magenta]Assignment:[/bold magenta]
  [yellow]⏳ Not assigned to any customer[/yellow]"""

        # Return the cable info for display
        return Panel(cable_info, title="📋 Cable Information", style="cyan")

    def show_not_found(self, operator, serial_number):
        """Show message when cable is not in database and return body content"""
        return Panel(
            f"❌ [bold red]Cable Not Found[/bold red]\n\n"
            f"Serial Number: [yellow]{serial_number}[/yellow]\n\n"
            f"This cable is not in the database.\n"
            f"It may not have been registered yet.",
            title="Not in Database", style="red"
        )


class CableSelectionForIntakeScreen(Screen):
    """Cable selection for registration workflow - goes directly to attribute selection"""
    def run(self) -> ScreenResult:
        # Go directly to series selection (attribute-based selection)
        new_context = self.context.copy()
        new_context["selection_mode"] = "intake"
        return ScreenResult(NavigationAction.REPLACE, SeriesSelectionScreen, new_context)


class SeriesSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        series_options = get_distinct_series()

        if not series_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No series found in database", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        # Create menu items
        menu_items = [f"{series}" for series in series_options]
        menu_items.append("Back (q)")

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Select the cable series", title="Step 1: Series Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Series"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ")
        except KeyboardInterrupt:
            print(f"\n\n🛑 Exiting {APP_NAME}...")
            print(EXIT_MESSAGE)
            sys.exit(0)

        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(series_options) + 1):
            return ScreenResult(NavigationAction.POP)

        # Handle series selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(series_options):
                selected_series = series_options[choice_idx]
                new_context = self.context.copy()
                new_context["selected_series"] = selected_series
                # Always go to attribute selection (color pattern)
                return ScreenResult(NavigationAction.REPLACE, ColorPatternSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice, stay on same screen
        return ScreenResult(NavigationAction.REPLACE, SeriesSelectionScreen, self.context)


class ColorPatternSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        color_options = get_distinct_color_patterns(selected_series)
        
        if not color_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(f"No color patterns found for {selected_series}", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        # Create menu items
        menu_items = [f"{color}" for color in color_options]
        menu_items.append("Back (q)")
        
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(f"Series: {selected_series}\nSelect the color/pattern", title="Step 2: Color Pattern Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Colors"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        
        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)
        
        # Handle color selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(color_options):
                selected_color = color_options[choice_idx]
                new_context = self.context.copy()
                new_context["selected_color_pattern"] = selected_color

                # Check if this is a MISC/Miscellaneous cable
                if selected_color.lower() in ['misc', 'miscellaneous']:
                    # Go to custom MISC cable entry screen
                    return ScreenResult(NavigationAction.REPLACE, MiscCableEntryScreen, new_context)
                else:
                    # Normal flow - go to length selection
                    return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice, stay on same screen
        return ScreenResult(NavigationAction.REPLACE, ColorPatternSelectionScreen, self.context)


class MiscCableEntryScreen(Screen):
    """Custom entry screen for MISC cables - prompts for length"""
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]Miscellaneous Cable Entry[/bold yellow]\n\n"
            f"Series: {selected_series}\n"
            f"Pattern: Miscellaneous (one-off/custom cable)\n\n"
            f"[bold cyan]Enter cable length in feet:[/bold cyan]\n"
            f"Examples: 3, 6, 10, 15, 20, 25\n\n"
            f"This will be used for the cable description.",
            title="MISC Cable - Enter Length",
            border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter length in feet (number only) or 'q' to go back",
            title="Length Entry"
        ))
        self.ui.render()

        try:
            length_input = self.ui.console.input("Length (ft): ").strip()

            if length_input.lower() == 'q':
                return ScreenResult(NavigationAction.POP)

            # Try to parse as a number
            try:
                length_value = float(length_input)
                if length_value <= 0:
                    self.ui.layout["body"].update(Panel(
                        "❌ Length must be greater than 0",
                        title="Invalid Length",
                        style="red"
                    ))
                    self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
                    self.ui.render()
                    self.ui.console.input()
                    return ScreenResult(NavigationAction.REPLACE, MiscCableEntryScreen, self.context)

                # Store the custom length
                new_context = self.context.copy()
                new_context["custom_length"] = length_value

                # Load the MISC SKU for this series
                # MISC SKUs follow pattern: SeriesPrefix-MISC (e.g., SC-MISC, TC-MISC)
                # Extract series prefix from the series name
                series_prefix_map = {
                    'Studio Classic': 'SC',
                    'Studio Patch': 'SP',
                    'Studio Vocal Classic': 'SV',
                    'Tour Classic': 'TC',
                    'Tour Vocal Classic': 'TV'
                }

                series_prefix = series_prefix_map.get(selected_series)
                if not series_prefix:
                    self.ui.layout["body"].update(Panel(
                        f"❌ Unknown series: {selected_series}",
                        title="Error",
                        style="red"
                    ))
                    self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
                    self.ui.render()
                    self.ui.console.input()
                    return ScreenResult(NavigationAction.POP)

                misc_sku = f"{series_prefix}-MISC"

                # Load the cable type
                try:
                    cable_type = CableType()
                    cable_type.load(misc_sku)

                    # Store cable type in context
                    new_context["cable_type"] = cable_type

                    # Go directly to scanning screen
                    return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)
                except ValueError as e:
                    self.ui.layout["body"].update(Panel(
                        f"❌ Error loading MISC SKU {misc_sku}: {str(e)}",
                        title="Error",
                        style="red"
                    ))
                    self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
                    self.ui.render()
                    self.ui.console.input()
                    return ScreenResult(NavigationAction.POP)

            except ValueError:
                self.ui.layout["body"].update(Panel(
                    f"❌ Invalid number: {length_input}\n\nPlease enter a valid number (e.g., 3, 6, 10, 15)",
                    title="Invalid Input",
                    style="red"
                ))
                self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
                self.ui.render()
                self.ui.console.input()
                return ScreenResult(NavigationAction.REPLACE, MiscCableEntryScreen, self.context)

        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)


class LengthSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        selected_color = self.context.get("selected_color_pattern")
        length_options = get_distinct_lengths(selected_series, selected_color)
        
        if not length_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(f"No lengths found for {selected_series} {selected_color}", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        # Create menu items
        menu_items = [f"{length} ft" for length in length_options]
        menu_items.append("Back (q)")
        
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(f"Series: {selected_series}\nColor: {selected_color}\nSelect the cable length", title="Step 3: Length Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Lengths"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        
        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)
        
        # Handle length selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(length_options):
                selected_length = length_options[choice_idx]
                new_context = self.context.copy()
                new_context["selected_length"] = selected_length
                return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)
        except ValueError:
            pass
        
        # Invalid choice, stay on same screen
        return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, self.context)


class ConnectorTypeSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        selected_color = self.context.get("selected_color_pattern")
        selected_length = self.context.get("selected_length")
        connector_options = get_distinct_connector_types(selected_series, selected_color, selected_length)
        
        if not connector_options:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(f"No connector types found for the selected attributes", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        # Create menu items
        menu_items = [f"{connector}" for connector in connector_options]
        menu_items.append("Back (q)")
        
        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(f"Series: {selected_series}\nColor: {selected_color}\nLength: {selected_length} ft\nSelect connector type", title="Step 4: Connector Selection"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Connectors"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        
        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)
        
        # Handle connector selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(connector_options):
                selected_connector = connector_options[choice_idx]
                
                # Find the actual cable SKU
                sku = find_cable_by_attributes(selected_series, selected_color, selected_length, selected_connector)
                
                if sku:
                    # Load the cable and go directly to scanning
                    try:
                        cable_type = CableType()
                        cable_type.load(sku)

                        # Store cable type in context
                        new_context = self.context.copy()
                        new_context["cable_type"] = cable_type

                        # Go directly to scanning screen without pause
                        return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)
                    except ValueError as e:
                        self.ui.layout["body"].update(Panel(f"Error loading cable: {str(e)}", title="Error", style="red"))
                        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
                        self.ui.render()
                        self.ui.console.input("")
                        return ScreenResult(NavigationAction.POP)
                else:
                    self.ui.layout["body"].update(Panel("No cable found with the selected attributes", title="Error", style="red"))
                    self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
                    self.ui.render()
                    self.ui.console.input("")
                    return ScreenResult(NavigationAction.POP)
        except ValueError:
            pass
        
        # Invalid choice, stay on same screen
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, self.context)


class CableTestScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        
        if not cable_type or not cable_type.is_loaded():
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No cable selected for testing", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        # Initialize tester
        # Create Arduino tester based on feature flag
        if USE_REAL_ARDUINO:
            try:
                tester = ArduinoATmega32Tester(port=ARDUINO_PORT, baudrate=ARDUINO_BAUDRATE)
                if not tester.initialize():
                    raise RuntimeError("Arduino initialization failed")
                logger.info("Using real Arduino ATmega32 tester")
            except ImportError as e:
                logger.warning(f"Arduino requires pyserial library: {e}")
                logger.warning("Install with: pip install pyserial")
                logger.info("Falling back to mock Arduino tester")
                tester = MockArduinoTester()
            except Exception as e:
                logger.warning(f"Failed to initialize real Arduino, falling back to mock: {e}")
                tester = MockArduinoTester()
        else:
            logger.info("Using mock Arduino tester (USE_REAL_ARDUINO=false)")
            tester = MockArduinoTester()
        resistance_range, capacitance_range = tester.get_expected_ranges(cable_type)
        
        # Show test start screen
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"Ready to test cable: {cable_type.sku}\n\n"
            f"Expected Ranges:\n"
            f"• Resistance: {resistance_range[0]}-{resistance_range[1]} Ω\n"
            f"• Capacitance: {capacitance_range[0]}-{capacitance_range[1]} pF\n\n"
            f"Connect cable to test fixture and press Enter to begin testing...",
            title="Cable Testing Setup"
        ))
        self.ui.layout["footer"].update(Panel("Press Enter to start test, 'q' to cancel", title=""))
        self.ui.render()
        
        choice = self.ui.console.input("Ready to test? ")
        if choice.lower() == 'q':
            return ScreenResult(NavigationAction.POP)
        
        # Run the actual test with real-time updates
        return self.run_test_sequence(operator, cable_type, tester)
    
    def run_test_sequence(self, operator, cable_type, tester):
        """Run the test sequence with real-time UI updates"""
        import time
        
        # Step 1: Continuity Test
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"Testing cable: {cable_type.sku}\n\n"
            f"🔍 CONTINUITY TEST\n"
            f"Status: Testing...\n\n"
            f"⏳ Resistance Test: Waiting...\n"
            f"⏳ Capacitance Test: Waiting...",
            title="Cable Testing - Step 1/3"
        ))
        self.ui.layout["footer"].update(Panel("Testing in progress...", title=""))
        self.ui.render()
        
        time.sleep(1.5)  # Simulate test time
        continuity_pass = tester.mock_continuity_test()
        continuity_status = "✅ PASS" if continuity_pass else "❌ FAIL"
        
        # Step 2: Resistance Test
        self.ui.layout["body"].update(Panel(
            f"Testing cable: {cable_type.sku}\n\n"
            f"✓ CONTINUITY TEST\n"
            f"Status: {continuity_status}\n\n"
            f"🔍 RESISTANCE TEST\n"
            f"Status: Testing...\n\n"
            f"⏳ Capacitance Test: Waiting...",
            title="Cable Testing - Step 2/3"
        ))
        self.ui.render()
        
        time.sleep(1.0)  # Simulate test time
        resistance = tester.mock_resistance_test(cable_type)
        resistance_range, _ = tester.get_expected_ranges(cable_type)
        resistance_pass = resistance_range[0] <= resistance <= resistance_range[1]
        resistance_status = "✅ PASS" if resistance_pass else "❌ FAIL"
        
        # Step 3: Capacitance Test
        self.ui.layout["body"].update(Panel(
            f"Testing cable: {cable_type.sku}\n\n"
            f"✓ CONTINUITY TEST\n"
            f"Status: {continuity_status}\n\n"
            f"✓ RESISTANCE TEST\n"
            f"Value: {resistance} Ω - {resistance_status}\n\n"
            f"🔍 CAPACITANCE TEST\n"
            f"Status: Testing...",
            title="Cable Testing - Step 3/3"
        ))
        self.ui.render()
        
        time.sleep(1.0)  # Simulate test time
        capacitance = tester.mock_capacitance_test(cable_type)
        _, capacitance_range = tester.get_expected_ranges(cable_type)
        capacitance_pass = capacitance_range[0] <= capacitance <= capacitance_range[1]
        capacitance_status = "✅ PASS" if capacitance_pass else "❌ FAIL"
        
        # Final Results
        overall_pass = continuity_pass and resistance_pass and capacitance_pass
        overall_status = "✅ PASS" if overall_pass else "❌ FAIL"
        result_style = "green" if overall_pass else "red"
        
        self.ui.layout["body"].update(Panel(
            f"Testing cable: {cable_type.sku}\n\n"
            f"✓ CONTINUITY TEST: {continuity_status}\n"
            f"✓ RESISTANCE TEST: {resistance} Ω - {resistance_status}\n"
            f"   Expected: {resistance_range[0]}-{resistance_range[1]} Ω\n"
            f"✓ CAPACITANCE TEST: {capacitance} pF - {capacitance_status}\n"
            f"   Expected: {capacitance_range[0]}-{capacitance_range[1]} pF\n\n"
            f"🎯 OVERALL RESULT: {overall_status}",
            title="Cable Testing - Complete", style=result_style
        ))
        
        if overall_pass:
            self.ui.layout["footer"].update(Panel("Press Enter to record cable, 'r' to run test again", title=""))
        else:
            self.ui.layout["footer"].update(Panel("Press Enter to continue, 'r' to run test again", title=""))
        self.ui.render()
        
        choice = self.ui.console.input("Test complete: ")
        if choice.lower() == 'r':
            return ScreenResult(NavigationAction.REPLACE, CableTestScreen, self.context)
        elif overall_pass:
            # Save passing cable to database and show record
            return self.record_passing_cable(operator, cable_type, tester, resistance, capacitance)
        else:
            return ScreenResult(NavigationAction.POP)
    
    def record_passing_cable(self, operator, cable_type, tester, resistance, capacitance):
        """Record passing cable to database and show tag printing option"""
        # Create test result for database insertion
        from greenlight.testing import TestResult
        from greenlight.db import update_cable_test_results, insert_audio_cable
        
        test_result = TestResult(
            continuity_pass=True,  # Only passing cables get here
            resistance_ohms=resistance,
            capacitance_pf=capacitance,
            test_time=0,  # Not used for database
            cable_sku=cable_type.sku,
            operator=operator,
            arduino_unit_id=tester.arduino_unit_id
        )
        
        # Check if this is testing an assembled cable with existing serial number
        existing_serial = self.context.get('serial_number')
        testing_mode = self.context.get('testing_mode')
        
        self.ui.layout["body"].update(Panel("Saving cable record to database...", title="Recording Cable"))
        self.ui.render()
        
        if existing_serial and testing_mode in ['assembled', 'retest']:
            # Update existing record with test results
            timestamp = update_cable_test_results(existing_serial, test_result)
            if timestamp:
                cable_record = {
                    'serial_number': existing_serial,
                    'timestamp': timestamp,
                    'sku': cable_type.sku
                }
            else:
                cable_record = None
        else:
            # Create new record (legacy workflow)
            cable_record = insert_audio_cable(cable_type, test_result)
        
        if cable_record:
            # Successfully saved - show the record and ask about tag printing
            return self.show_cable_record(cable_record, cable_type, test_result)
        else:
            # Database error
            self.ui.layout["body"].update(Panel(
                "❌ Failed to save cable record to database.\n\n"
                "The cable passed testing but could not be recorded.\n"
                "Please check database connection and try again.",
                title="Database Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press Enter to continue", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
    
    def show_cable_record(self, cable_record, cable_type, test_result):
        """Display the saved cable record and ask about tag printing"""
        from greenlight.hardware.interfaces import hardware_manager
        
        serial_number = cable_record['serial_number']
        timestamp = cable_record['timestamp']
        
        # Format timestamp for display
        if hasattr(timestamp, 'strftime'):
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_str = str(timestamp)
        
        # Check if card printer is available for QC cards
        card_printer_available = hardware_manager.card_printer and hardware_manager.card_printer.is_ready()
        
        self.ui.layout["body"].update(Panel(
            f"🎉 Cable Recorded Successfully!\n\n"
            f"Serial Number: {serial_number}\n"
            f"SKU: {cable_type.sku}\n"
            f"Name: {cable_type.name()}\n"
            f"Series: {cable_type.series}\n"
            f"Length: {cable_type.length} ft\n"
            f"Color: {cable_type.color_pattern}\n"
            f"Connector: {cable_type.connector_type}\n\n"
            f"Test Results:\n"
            f"  • Resistance: {test_result.resistance_ohms} Ω\n"
            f"  • Capacitance: {test_result.capacitance_pf} pF\n"
            f"Operator: {test_result.operator}\n"
            f"Testing Unit: Arduino #{test_result.arduino_unit_id}\n"
            f"Timestamp: {timestamp_str}",
            title="Production Record", style="green"
        ))
        
        if card_printer_available:
            self.ui.layout["footer"].update(Panel("Print QC card? (y/n) or Enter to continue", title=""))
        else:
            self.ui.layout["footer"].update(Panel("Enter to continue", title=""))
        
        self.ui.render()
        
        if card_printer_available:
            choice = self.ui.console.input("Print QC card? ").lower()
            if choice == 'y' or choice == 'yes':
                return self.print_qc_card(cable_record, cable_type, test_result, timestamp_str)
        else:
            self.ui.console.input("Press enter to continue...")
        
        return ScreenResult(NavigationAction.POP)
    
    def print_qc_card(self, cable_record, cable_type, test_result, timestamp_str):
        """Print QC result card for the tested cable"""
        from greenlight.hardware.interfaces import hardware_manager, PrintJob
        
        serial_number = cable_record['serial_number']
        
        # Show printing in progress
        self.ui.layout["body"].update(Panel(
            f"🖨️  Printing QC card for {serial_number}...\n\n"
            f"Cable: {cable_type.name()}\n"
            f"Test Results: PASS\n\n"
            f"Please wait while card is printed...",
            title="Printing QC Card", style="blue"
        ))
        self.ui.layout["footer"].update(Panel("Printing in progress...", title="Status"))
        self.ui.render()
        
        # Create print job for QC card
        print_job = PrintJob(
            template="qc_card",
            data={
                'serial_number': serial_number,
                'sku': cable_type.sku,
                'cable_name': cable_type.name(),
                'test_results': {
                    'resistance_ohms': test_result.resistance_ohms,
                    'capacitance_pf': test_result.capacitance_pf,
                    'pass': True
                },
                'operator': test_result.operator,
                'test_date': timestamp_str
            }
        )
        
        # Send to card printer
        print_success = hardware_manager.card_printer.print_qc_card(print_job)
        
        if print_success:
            self.ui.layout["body"].update(Panel(
                f"✅ QC card printed successfully!\n\n"
                f"Serial Number: {serial_number}\n"
                f"Cable: {cable_type.name()}\n"
                f"Test Result: PASS\n\n"
                f"QC card is ready for customer shipment.",
                title="QC Card Complete", style="green"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"❌ QC card printing failed\n\n"
                f"Cable testing and recording completed successfully,\n"
                f"but QC card could not be printed.\n\n"
                f"Please check card printer and try again if needed.",
                title="Print Error", style="red"
            ))
        
        self.ui.layout["footer"].update(Panel("Press enter to continue", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class PrintCableTagScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_record = self.context.get("cable_record")
        cable_serial = self.context.get("cable_serial")
        
        self.ui.header(operator)
        
        if cable_record and cable_serial:
            # Show tag printing for specific cable
            self.ui.layout["body"].update(Panel(
                f"🏷️  CABLE TAG PRINTING\n\n"
                f"Serial Number: {cable_serial}\n"
                f"SKU: {cable_record['sku']}\n\n"
                f"Tag printing functionality coming soon...\n"
                f"This will print a physical tag with QR code and cable information.",
                title="Print Cable Tag"
            ))
        else:
            # General tag printing
            self.ui.layout["body"].update(Panel(
                "🏷️  CABLE TAG PRINTING\n\n"
                "General tag printing functionality coming soon...",
                title="Print Cable Tag"
            ))
        
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


class PrintCableWrapScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Print cable wrap functionality coming soon", title="Print Cable Wrap"))
        self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
        self.ui.render()
        
        self.ui.console.input("Press enter to continue...")
        return ScreenResult(NavigationAction.POP)


# ============================================================================
# Additional Cable Screens (from new_screens.py)
# ============================================================================


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

        # Check if this is a MISC SKU that needs custom description
        cable_description = None
        if cable_type.sku.endswith("-MISC"):
            cable_description = self.get_misc_cable_description(operator, cable_type)
            if cable_description is None:
                # User cancelled
                return ScreenResult(NavigationAction.POP)

        # Show scanning interface
        return self.scan_cables_loop(operator, cable_type, cable_description)

    def get_misc_cable_description(self, operator, cable_type):
        """Prompt for custom description for miscellaneous cable

        Returns:
            Description string, or None if user cancels
        """
        self.ui.console.clear()
        self.ui.header(operator)

        # Get custom length from context if available
        custom_length = self.context.get("custom_length")
        length_info = ""
        if custom_length:
            # Format length nicely
            if custom_length == int(custom_length):
                length_str = f"{int(custom_length)}ft"
            else:
                length_str = f"{custom_length}ft"
            length_info = f"Length: [bold green]{length_str}[/bold green]\n"

        self.ui.layout["body"].update(Panel(
            f"[bold yellow]Miscellaneous Cable Registration[/bold yellow]\n\n"
            f"SKU: {cable_type.sku}\n"
            f"Series: {cable_type.series}\n"
            f"{length_info}\n"
            f"This is a miscellaneous (MISC) SKU for one-off and oddball cables\n"
            f"that don't fit standard definitions.\n\n"
            f"[bold cyan]Please enter a description for this cable:[/bold cyan]\n"
            f"[dim](Length is already stored separately - don't include it here)[/dim]\n\n"
            f"Include details like:\n"
            f"  • Color/pattern (e.g., 'custom blue/orange')\n"
            f"  • Connector types (e.g., 'Neutrik TS-TRS')\n"
            f"  • Cable construction (e.g., 'cotton braid')\n"
            f"  • Any special attributes\n\n"
            f"Example: 'dark putty houndstooth with gold connectors instead of nickel'",
            title="📝 Custom Cable Description",
            border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter description or 'q' to cancel",
            title="Description"
        ))
        self.ui.render()

        try:
            description = self.ui.console.input("Description: ").strip()
            if description.lower() == 'q' or not description:
                return None

            # Return description as-is (length is stored separately in audio_cables.length)
            return description
        except KeyboardInterrupt:
            return None

    def scan_cables_loop(self, operator, cable_type, cable_description=None):
        """Main scanning loop for registering multiple cables

        Args:
            operator: Operator ID
            cable_type: CableType object
            cable_description: Optional custom description for MISC SKUs
        """
        from greenlight.db import register_scanned_cable

        # Get custom length from context if this is a MISC cable
        custom_length = self.context.get("custom_length")

        scanned_count = 0
        scanned_serials = []

        while True:
            # Clear console before rendering to avoid layout corruption
            self.ui.console.clear()

            # Show current status
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Property", style="cyan", width=20)
            table.add_column("Value", style="green")

            table.add_row("Cable Type", cable_type.name())
            table.add_row("SKU", cable_type.sku)
            if cable_description:
                table.add_row("Description", cable_description)
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

            # Clear and show confirmation screen with scanned serial number
            self.ui.console.clear()
            serial_display = f"[bold yellow]{formatted_serial}[/bold yellow]"

            self.ui.header(operator)
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

            # For MISC cables, always try to update if exists (to add/update description)
            is_misc_cable = cable_type.sku.endswith("-MISC")

            # Register the cable in database (note: formatted_serial is already formatted in register_scanned_cable)
            result = register_scanned_cable(serial_number, cable_type.sku, operator,
                                          update_if_exists=is_misc_cable,
                                          description=cable_description,
                                          length=custom_length)

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

                # Offer to print label
                self.offer_print_label(operator, cable_type, saved_serial, custom_length, cable_description)
            else:
                # Error registering
                error_type = result.get('error', 'unknown')
                error_msg = result.get('message', 'Unknown error')

                if error_type == 'duplicate':
                    # Cable already exists
                    from greenlight.db import get_audio_cable
                    cable_record = get_audio_cable(formatted_serial)

                    if cable_record:
                        # For non-MISC cables, show the detailed cable info
                        # For MISC cables, this shouldn't happen since we set update_if_exists=True
                        self.show_cable_info_inline(operator, cable_record)
                        # Continue to next scan
                        continue
                    else:
                        # Fallback to duplicate prompt if we can't get the record
                        existing = result.get('existing_record', {})
                        user_choice = self.show_duplicate_prompt(operator, cable_type, existing)

                        if user_choice == 'quit':
                            # User wants to quit scanning
                            break
                        elif user_choice == 'update':
                            # User chose to update - retry with update flag
                            update_result = register_scanned_cable(serial_number, cable_type.sku, operator,
                                                                  update_if_exists=True,
                                                                  description=cable_description,
                                                                  length=custom_length)
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

        # Go back to SKU selection screen
        return ScreenResult(NavigationAction.REPLACE, CableSelectionForIntakeScreen, self.context)

    def offer_print_label(self, operator, cable_type, serial_number, custom_length=None, cable_description=None):
        """Offer to print a label for the registered cable

        Args:
            operator: Operator ID
            cable_type: CableType object
            serial_number: Registered serial number
            custom_length: Optional custom length for MISC cables
            cable_description: Optional description for MISC cables
        """
        from greenlight.hardware.interfaces import hardware_manager, PrintJob

        # Check if label printer is available
        label_printer = hardware_manager.get_label_printer()
        if not label_printer or not label_printer.is_ready():
            # Printer not available, skip label printing
            return

        # Clear console and show print prompt
        self.ui.console.clear()
        self.ui.header(operator)

        self.ui.layout["body"].update(Panel(
            f"[bold green]✅ Cable Registered[/bold green]\n\n"
            f"Serial Number: {serial_number}\n"
            f"SKU: {cable_type.sku}\n"
            f"Cable: {cable_type.name()}\n\n"
            f"[bold yellow]Print label now?[/bold yellow]",
            title="🏷️  Label Printing",
            border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "[green]y[/green] = Print label | [cyan]n[/cyan] = Skip | [yellow]Enter[/yellow] = Skip",
            title="Print Label?"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()

            if choice == 'y' or choice == 'yes':
                # Print the label
                self.print_cable_label(operator, cable_type, serial_number, custom_length, cable_description)

        except KeyboardInterrupt:
            pass

    def print_cable_label(self, operator, cable_type, serial_number, custom_length=None, cable_description=None):
        """Print a cable label

        Args:
            operator: Operator ID
            cable_type: CableType object
            serial_number: Cable serial number
            custom_length: Optional custom length for MISC cables
            cable_description: Optional description for MISC cables
        """
        from greenlight.hardware.interfaces import hardware_manager, PrintJob

        label_printer = hardware_manager.get_label_printer()
        if not label_printer:
            return

        # Show printing in progress
        self.ui.console.clear()
        self.ui.header(operator)

        self.ui.layout["body"].update(Panel(
            f"🖨️  Printing label...\n\n"
            f"Serial: {serial_number}\n"
            f"SKU: {cable_type.sku}\n\n"
            f"Please wait...",
            title="Printing Label", style="blue"
        ))
        self.ui.render()

        # Prepare label data
        label_data = {
            'series': cable_type.series,
            'length': custom_length if custom_length else cable_type.length,
            'color_pattern': cable_type.color_pattern,
            'connector_type': cable_type.connector_type,
            'sku': cable_type.sku,
        }

        # Add description for MISC cables
        if cable_description:
            label_data['description'] = cable_description

        # Create print job
        print_job = PrintJob(
            template="cable_label",
            data=label_data,
            quantity=1
        )

        # Send to printer
        success = label_printer.print_labels(print_job)

        # Show result
        self.ui.console.clear()
        self.ui.header(operator)

        if success:
            self.ui.layout["body"].update(Panel(
                f"✅ [bold green]Label Printed Successfully![/bold green]\n\n"
                f"Serial: {serial_number}\n"
                f"SKU: {cable_type.sku}\n\n"
                f"Label ready to apply to cable.",
                title="Print Complete", style="green"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"❌ [bold red]Label Printing Failed[/bold red]\n\n"
                f"Serial: {serial_number}\n"
                f"SKU: {cable_type.sku}\n\n"
                f"Please check printer and try again.",
                title="Print Error", style="red"
            ))

        self.ui.layout["footer"].update(Panel("Press enter to continue scanning", title=""))
        self.ui.render()

        # Brief pause to show result
        try:
            self.ui.console.input("")
        except KeyboardInterrupt:
            pass

    def show_cable_info_inline(self, operator, cable_record):
        """Display detailed cable information during scanning workflow"""
        self.ui.console.clear()

        serial_number = cable_record.get("serial_number", "N/A")
        sku = cable_record.get("sku", "N/A")
        series = cable_record.get("series", "N/A")
        length = cable_record.get("length", "N/A")
        color_pattern = cable_record.get("color_pattern", "N/A")
        connector_type = cable_record.get("connector_type", "N/A")
        resistance_ohms = cable_record.get("resistance_ohms")
        capacitance_pf = cable_record.get("capacitance_pf")
        cable_operator = cable_record.get("operator", "N/A")
        test_timestamp = cable_record.get("test_timestamp")
        updated_timestamp = cable_record.get("updated_timestamp")

        # Format test results
        if resistance_ohms is not None:
            resistance_str = f"{resistance_ohms:.2f} Ω"
            test_status = "✅ Tested"
        else:
            resistance_str = "Not tested"
            test_status = "⏳ Not tested"

        if capacitance_pf is not None:
            capacitance_str = f"{capacitance_pf:.2f} pF"
        else:
            capacitance_str = "Not tested"

        # Format timestamps
        if test_timestamp:
            if hasattr(test_timestamp, 'strftime'):
                test_timestamp_str = test_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                test_timestamp_str = str(test_timestamp)
        else:
            test_timestamp_str = "Not tested"

        if updated_timestamp:
            if hasattr(updated_timestamp, 'strftime'):
                updated_timestamp_str = updated_timestamp.strftime("%Y-%m-%d %H:%M:%S")
            else:
                updated_timestamp_str = str(updated_timestamp)
        else:
            updated_timestamp_str = "N/A"

        # Build cable info display
        cable_info = f"""[bold yellow]Serial Number:[/bold yellow] {serial_number}
[bold yellow]SKU:[/bold yellow] {sku}
[bold yellow]Registered:[/bold yellow] {updated_timestamp_str}

[bold cyan]Cable Details:[/bold cyan]
  Series: {series}
  Length: {length} ft
  Color: {color_pattern}
  Connector: {connector_type}"""

        # Add description for MISC cables
        description = cable_record.get("description")
        if sku.endswith("-MISC") and description:
            cable_info += f"\n  Description: {description}"

        cable_info += f"""

[bold green]Test Status:[/bold green] {test_status}
  Resistance: {resistance_str}
  Capacitance: {capacitance_str}
  Tested: {test_timestamp_str}
  Test Operator: {cable_operator if test_timestamp else 'N/A'}"""

        # Check if cable is assigned to a customer
        customer_gid = cable_record.get("shopify_gid")

        if customer_gid:
            # Cable is assigned - fetch customer details
            from greenlight import shopify_client
            customer_numeric_id = customer_gid.split('/')[-1]
            customer = shopify_client.get_customer_by_id(customer_numeric_id)

            if customer:
                customer_name = customer.get("displayName") or "N/A"
                customer_email = customer.get("email") or "N/A"
                customer_phone = customer.get("phone")
                address = customer.get("defaultAddress")
                if not customer_phone and address:
                    customer_phone = address.get("phone")
                customer_phone = customer_phone or "N/A"

                cable_info += f"""

[bold magenta]✅ Assigned To Customer:[/bold magenta]
  Name: {customer_name}
  Email: {customer_email}
  Phone: {customer_phone}"""
            else:
                cable_info += f"""

[bold magenta]Assigned To:[/bold magenta]
  [yellow]Customer ID: {customer_gid}[/yellow]
  [dim](Details not available)[/dim]"""
        else:
            cable_info += """

[bold magenta]Assignment:[/bold magenta]
  [yellow]⏳ Not assigned to any customer[/yellow]"""

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(cable_info, title="📋 Cable Information (Already Registered)", style="cyan"))
        self.ui.layout["footer"].update(Panel(
            "Press enter to scan another cable",
            title=""
        ))
        self.ui.render()
        self.ui.console.input()

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
            # Wait indefinitely for either a scan or keyboard input
            # No timeout - user must explicitly quit with 'q'
            while True:
                # Check for scanned barcode
                if scanner_available:
                    barcode = scanner.get_scan(timeout=0.1)
                    if barcode:
                        serial_number = barcode.strip().upper()
                        # Return immediately without printing (confirmation screen will show it)
                        return serial_number

                # Check for manual keyboard input
                if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                    line = sys.stdin.readline().strip().upper()
                    if line:
                        if line == 'Q':
                            return None
                        return line

                time.sleep(0.1)  # Small sleep to prevent busy-waiting (increased from 0.05 to 0.1)

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
            return ScreenResult(NavigationAction.POP, pop_count=1)

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
        return ScreenResult(NavigationAction.POP, pop_count=1)


