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
from greenlight.db import insert_audio_cable, get_audio_cable
from greenlight.new_screens import PrintLabelsScreen, TestAssembledCableScreen


class CableQCScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        
        # Simple two-option menu
        menu_items = [
            "Test Cables",
            "Print Cable Labels", 
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "Audio Cable Management\n\n"
            "• Test Cables - Scan serial number from assembled cable and run QC tests\n"
            "• Print Cable Labels - Select cable type and print labels for assembly team",
            title="Cable Management Options"
        ))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Audio Cable Management"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        
        if choice == "1":  # Test Cables
            return ScreenResult(NavigationAction.PUSH, TestAssembledCableScreen, self.context)
        elif choice == "2":  # Print Cable Labels
            return ScreenResult(NavigationAction.PUSH, CableSelectionScreen, self.context)
        elif choice == "3" or choice.lower() == "q":  # Back
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, CableQCScreen, self.context)


class CableSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        menu_items = [
            "Enter SKU",
            "Select By Attribute",
            "Back (q)"
        ]

        rows = [
            f"[green]{i + 1}.[/green] {name}"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel("Choose how to select cable type for label printing", title="Cable Selection for Labels"))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Selection Method"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice == "1":
            return ScreenResult(NavigationAction.REPLACE, SKUEntryScreen, self.context)
        elif choice == "2":
            return ScreenResult(NavigationAction.REPLACE, AttributeSelectionScreen, self.context)
        elif choice == "3" or choice.lower() == "q":
            return ScreenResult(NavigationAction.POP)
        else:
            return ScreenResult(NavigationAction.REPLACE, CableSelectionScreen, self.context)


class SKUEntryScreen(Screen):
    def run(self) -> ScreenResult:
        # This screen is just a redirect - go directly to series selection
        # Set context to indicate this is for SKU selection workflow
        new_context = self.context.copy()
        new_context["selection_mode"] = "sku"
        return ScreenResult(NavigationAction.REPLACE, SeriesSelectionScreen, new_context)



class SKUListSelectionScreen(Screen):
    def get_skus_for_series(self, series):
        """Get all SKUs for a specific series"""
        from greenlight.cable import pg_pool
        conn = pg_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT sku FROM cable_skus WHERE series = %s ORDER BY sku", (series,))
                return [row[0] for row in cur.fetchall()]
        except Exception as e:
            print(f"Error fetching SKUs: {e}")
            return []
        finally:
            pg_pool.putconn(conn)
    
    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        
        # Get SKUs for the selected series
        skus = self.get_skus_for_series(selected_series)
        
        if not skus:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(f"No SKUs found for {selected_series}", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)
        
        # Create numbered menu for SKUs
        menu_items = skus.copy()
        menu_items.append("Back (q)")
        
        # Format as numbered list in multiple columns for better space usage
        sku_items = []
        for i, sku in enumerate(skus):
            sku_items.append(f"[green]{i + 1:2d}.[/green] {sku}")
        sku_items.append(f"[green]{len(skus) + 1:2d}.[/green] Back (q)")
        
        # Arrange in 2 columns to fit more on screen
        rows = []
        for i in range(0, len(sku_items), 2):
            left_item = sku_items[i]
            right_item = sku_items[i + 1] if i + 1 < len(sku_items) else ""
            # Pad left item to consistent width for alignment
            left_padded = f"{left_item:<35}"
            rows.append(f"{left_padded} {right_item}")
        
        sku_display = "\n".join(rows)
        
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(sku_display, title=f"Available {selected_series} SKUs - Choose a number:"))
        self.ui.layout["footer"].update(Panel("Enter the number of your choice:", title="Selection"))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ")
        except KeyboardInterrupt:
            print(f"\n\n🛑 Exiting {APP_NAME}...")
            print(EXIT_MESSAGE)
            sys.exit(0)
        
        # Handle back/quit
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)
        
        # Handle SKU selection
        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(skus):
                selected_sku = skus[choice_idx]
                return self.load_selected_sku(selected_sku)
        except ValueError:
            pass
        
        # Invalid choice, stay on same screen
        return ScreenResult(NavigationAction.REPLACE, SKUListSelectionScreen, self.context)
    
    def load_selected_sku(self, sku):
        """Load the selected SKU and return to cable QC screen"""
        try:
            cable_type = CableType()
            cable_type.load(sku)
            
            # Store cable type in context
            new_context = self.context.copy()
            new_context["cable_type"] = cable_type
            
            # Show success
            self.ui.layout["body"].update(Panel(
                f"Successfully loaded cable: {sku}\n\n{cable_type.name()}", 
                title="Success", style="green"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to continue...", title=""))
            self.ui.render()
            self.ui.console.input("")
            
            # Navigate directly to PrintLabelsScreen with selected cable
            return ScreenResult(NavigationAction.REPLACE, PrintLabelsScreen, new_context)
        except ValueError as e:
            # Show error
            self.ui.layout["body"].update(Panel(f"Error loading {sku}: {str(e)}", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to try again...", title=""))
            self.ui.render()
            self.ui.console.input("")
            return ScreenResult(NavigationAction.REPLACE, SKUListSelectionScreen, self.context)


class AttributeSelectionScreen(Screen):
    def run(self) -> ScreenResult:
        # Start the attribute selection flow with series selection
        # Set context to indicate this is for attribute selection workflow
        new_context = self.context.copy()
        new_context["selection_mode"] = "attribute"
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
                
                # Route based on selection mode
                selection_mode = self.context.get("selection_mode", "attribute")
                if selection_mode == "sku":
                    return ScreenResult(NavigationAction.REPLACE, SKUListSelectionScreen, new_context)
                else:  # attribute mode
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
                return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, new_context)
        except ValueError:
            pass
        
        # Invalid choice, stay on same screen
        return ScreenResult(NavigationAction.REPLACE, ColorPatternSelectionScreen, self.context)


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
                    # Load the cable and show success
                    try:
                        cable_type = CableType()
                        cable_type.load(sku)
                        
                        # Store cable type in context
                        new_context = self.context.copy()
                        new_context["cable_type"] = cable_type
                        
                        self.ui.layout["body"].update(Panel(
                            f"Successfully found cable:\n\nSKU: {sku}\nSeries: {selected_series}\nColor: {selected_color}\nLength: {selected_length} ft\nConnector: {selected_connector}", 
                            title="Cable Found!", style="green"
                        ))
                        self.ui.layout["footer"].update(Panel("Press enter to continue...", title=""))
                        self.ui.render()
                        self.ui.console.input("")
                        
                        # Navigate directly to PrintLabelsScreen with selected cable
                        return ScreenResult(NavigationAction.REPLACE, PrintLabelsScreen, new_context)
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