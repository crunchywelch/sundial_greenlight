from rich.panel import Panel
import logging

logger = logging.getLogger(__name__)
import sys
import termios
import tty
import readline

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import APP_NAME, EXIT_MESSAGE
from greenlight.cable import (
    CableType, get_all_skus, filter_skus, get_distinct_series, 
    get_distinct_color_patterns, get_distinct_lengths, get_distinct_connector_types,
    find_cable_by_attributes
)
from greenlight.db import get_audio_cable, register_scanned_cable, format_serial_number, update_cable_test_results
from rich.table import Table
import time


class ScanCableLookupScreen(Screen):
    """Main cable interface - scan to lookup, test, assign, or register cables"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        # Check if we're returning from assignment and should show cable details
        return_to_cable = self.context.get("return_to_cable_serial")
        if return_to_cable:
            # Clear the return flag
            self.context.pop("return_to_cable_serial", None)
            # Load and show the cable details
            from greenlight.db import get_audio_cable
            cable_record = get_audio_cable(return_to_cable)
            if cable_record:
                action_result = self.show_cable_info_with_actions(operator, cable_record)
                if action_result:
                    return action_result

        # Initial body content
        body_panel = Panel(
            "🔍 Ready to Scan\n\n"
            "Scan a cable barcode to:\n"
            "  • View cable information\n"
            "  • Run continuity/resistance tests\n"
            "  • Assign to customer\n"
            "  • Print label\n\n"
            "[dim]Waiting for scan...[/dim]",
            title="Greenlight Cable Station"
        )

        self._pending_serial = None

        while True:
            # Check if we have a pending serial from the cable info screen
            if self._pending_serial:
                serial_number = self._pending_serial
                self._pending_serial = None
            else:
                # Update display
                self.ui.header(operator)
                self.ui.layout["body"].update(body_panel)
                self.ui.layout["footer"].update(Panel(
                    "🔍 [bold green]Scan barcode[/bold green] | "
                    "[cyan]'r'[/cyan] = Register cables | "
                    "[cyan]'w'[/cyan] = Wholesale codes | "
                    "[cyan]'p'[/cyan] = Wire labels | "
                    "[cyan]'q'[/cyan] = Logout",
                    title="Options", border_style="green"
                ))
                self.ui.render()

                # Get serial number or menu command
                serial_number = self.get_serial_number_scan_or_manual()

            # Check for menu commands
            if not serial_number:
                continue

            input_lower = serial_number.lower()

            if input_lower == 'q':
                # Logout - go back to operator selection
                return ScreenResult(NavigationAction.POP)
            elif input_lower == 'r':
                # Go to register cables flow
                new_context = self.context.copy()
                new_context["selection_mode"] = "intake"
                return ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, new_context)
            elif input_lower == 'w':
                # Go to wholesale batch registration codes
                from greenlight.screens.wholesale import WholesaleBatchScreen
                return ScreenResult(NavigationAction.PUSH, WholesaleBatchScreen, self.context.copy())
            elif input_lower == 'p':
                # Go to wire label printing
                from greenlight.screens.wire import WireLabelScreen
                return ScreenResult(NavigationAction.PUSH, WireLabelScreen, self.context.copy())

            # Otherwise treat as serial number lookup
            from greenlight.db import format_serial_number, get_audio_cable
            formatted_serial = format_serial_number(serial_number)
            cable_record = get_audio_cable(formatted_serial)

            # Clear console to refresh with new info
            self.ui.console.clear()

            if cable_record:
                # Show cable info and handle user actions
                action_result = self.show_cable_info_with_actions(operator, cable_record)
                if action_result:
                    return action_result
                # If no action result, continue scanning
                body_panel = Panel(
                    "🔍 Ready to Scan\n\n"
                    "[dim]Waiting for next cable...[/dim]",
                    title="Greenlight Cable Station"
                )
            else:
                # Cable not found - offer to register
                register_result = self.show_not_found_with_register(operator, formatted_serial)
                if register_result:
                    return register_result
                # If no result, continue scanning
                body_panel = Panel(
                    "🔍 Ready to Scan\n\n"
                    "[dim]Waiting for scan...[/dim]",
                    title="Greenlight Cable Station"
                )

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
        """Display cable info and prompt for action (test, assign, print, or continue)

        Returns:
            ScreenResult if user wants to assign to customer, None to continue scanning
        """
        # Display cable info
        cable_info_panel = self.build_cable_info_panel(cable_record)

        self.ui.header(operator)
        self.ui.layout["body"].update(cable_info_panel)

        # Check if cable is already assigned and if printer is available
        customer_gid = cable_record.get("shopify_gid")

        # Check if label printer is available
        from greenlight.hardware.interfaces import hardware_manager
        label_printer = hardware_manager.get_label_printer()
        printer_available = label_printer and label_printer.is_ready() if label_printer else False

        # Check if cable tester is available
        cable_tester = hardware_manager.get_cable_tester()
        tester_available = cable_tester and cable_tester.is_ready() if cable_tester else False

        # Check if cable has been tested
        cable_tested = cable_record.get('test_passed') is True

        # Check if this is a MISC cable (editable description)
        is_misc = cable_record.get('sku', '').endswith('-MISC')

        # Build footer text based on options
        footer_options = []
        if tester_available:
            footer_options.append("[cyan]'t'[/cyan] = Test cable")
        footer_options.append("[cyan]'a'[/cyan] = Assign cable")
        if printer_available and cable_tested:
            footer_options.append("[cyan]'p'[/cyan] = Print label")
        if is_misc:
            footer_options.append("[cyan]'d'[/cyan] = Edit description")
        footer_options.append("[bold green]Scan[/bold green] next cable")

        footer_text = " | ".join(footer_options)

        self.ui.layout["footer"].update(Panel(footer_text, title="Options"))
        self.ui.render()

        try:
            choice = self.get_serial_number_scan_or_manual()
            if not choice:
                return None
            choice_lower = choice.strip().lower()

            if choice_lower == 't' and tester_available:
                # Run cable tests
                self.run_cable_test(operator, cable_record)
                # Refresh cable record and show details again
                from greenlight.db import get_audio_cable
                updated_record = get_audio_cable(cable_record['serial_number'])
                if updated_record:
                    return self.show_cable_info_with_actions(operator, updated_record)
                return None

            elif choice_lower == 'a':
                # Push customer lookup screen with cable serial in context
                from greenlight.screens.orders import CustomerLookupScreen
                new_context = self.context.copy()
                new_context["assign_cable_serial"] = cable_record['serial_number']
                new_context["assign_cable_sku"] = cable_record['sku']
                new_context["return_to_cable_serial"] = cable_record['serial_number']
                return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, new_context)

            elif choice_lower == 'p' and printer_available and cable_tested:
                # Print label for this cable
                self.print_label_for_cable(operator, cable_record)
                # Go back to cable details
                return self.show_cable_info_with_actions(operator, cable_record)

            elif choice_lower == 'd' and is_misc:
                # Edit description for MISC cable
                updated_record = self.edit_cable_description(operator, cable_record)
                return self.show_cable_info_with_actions(operator, updated_record)

            else:
                # Input is not a command — treat as a new serial number scan
                self._pending_serial = choice.strip().upper()
                return None

        except KeyboardInterrupt:
            return None

    def print_label_for_cable(self, operator, cable_record):
        """Print a label for an existing cable from the database

        Args:
            operator: Operator ID
            cable_record: Cable record from database
        """
        from greenlight.hardware.interfaces import hardware_manager, PrintJob

        label_printer = hardware_manager.get_label_printer()
        if not label_printer:
            return

        serial_number = cable_record.get('serial_number')
        sku = cable_record.get('sku')
        series = cable_record.get('series')
        length = cable_record.get('length')
        color_pattern = cable_record.get('color_pattern')
        connector_type = cable_record.get('connector_type')
        description = cable_record.get('description')
        test_passed = cable_record.get('test_passed')
        cable_operator = cable_record.get('operator')

        # Prepare label data
        label_data = {
            'serial_number': serial_number,
            'series': series,
            'length': length,
            'color_pattern': color_pattern,
            'connector_type': connector_type,
            'sku': sku,
        }

        # Add description: per-cable for MISC, SKU pattern description for standard
        if description:
            label_data['description'] = description
        elif cable_record.get('sku_description'):
            label_data['description'] = cable_record['sku_description']

        # Add test results if cable has been tested and passed
        if test_passed is True:
            label_data['test_results'] = {
                'continuity_pass': True,
                'resistance_pass': True,
                'operator': cable_operator or operator,
                'test_timestamp': cable_record.get('test_timestamp'),
            }

        # Create print job and send to printer
        print_job = PrintJob(
            template="cable_label",
            data=label_data,
            quantity=1
        )
        label_printer.print_labels(print_job)

    def edit_cable_description(self, operator, cable_record):
        """Prompt operator to edit description for a MISC cable

        Args:
            operator: Operator ID
            cable_record: Cable record from database

        Returns:
            Updated cable record
        """
        serial_number = cable_record.get('serial_number')
        current_desc = cable_record.get('description', '')

        self.ui.console.clear()
        self.ui.header(operator)

        max_desc_len = 90
        prefill_text = None

        try:
            while True:
                self.ui.console.clear()
                self.ui.header(operator)

                prompt_text = f"Serial: {serial_number}\n\n"
                if current_desc:
                    prompt_text += f"Current description: {current_desc}\n\n"
                else:
                    prompt_text += "No description set.\n\n"
                if prefill_text:
                    prompt_text += f"[red]Too long ({len(prefill_text)}/{max_desc_len} chars) — please shorten:[/red]"
                else:
                    prompt_text += f"Enter new description, max {max_desc_len} chars (or press Enter to cancel):"

                self.ui.layout["body"].update(Panel(prompt_text, title="Edit Description", style="yellow"))
                self.ui.layout["footer"].update(Panel(f"Max {max_desc_len} characters", title=""))
                self.ui.render()

                # Pre-fill input with previous too-long text so user can edit in place
                if prefill_text:
                    readline.set_startup_hook(lambda: readline.insert_text(prefill_text))
                else:
                    readline.set_startup_hook(None)

                try:
                    new_desc = self.ui.console.input("").strip()
                finally:
                    readline.set_startup_hook(None)

                if not new_desc:
                    return cable_record

                if len(new_desc) > max_desc_len:
                    prefill_text = new_desc
                    continue

                from greenlight.db import update_cable_description, get_audio_cable
                if update_cable_description(serial_number, new_desc):
                    updated = get_audio_cable(serial_number)
                    if updated:
                        return updated
                return cable_record
        except KeyboardInterrupt:
            return cable_record

    def run_cable_test(self, operator, cable_record):
        """Run cable tests and save results. Routes to TS or XLR test flow.

        Args:
            operator: Operator ID
            cable_record: Cable record from database
        """
        connector_type = cable_record.get('connector_type', '').upper()
        series = cable_record.get('series', '').lower()
        if 'XLR' in connector_type or 'vocal' in series:
            self._run_xlr_cable_test(operator, cable_record)
        else:
            self._run_ts_cable_test(operator, cable_record)

    def _run_ts_cable_test(self, operator, cable_record):
        """Run TS cable tests (continuity and resistance) and save results

        Shows test progress and results in the footer while keeping cable details visible.
        If the tester is not calibrated, prompts the user to calibrate first.

        Args:
            operator: Operator ID
            cable_record: Cable record from database
        """
        from greenlight.hardware.interfaces import hardware_manager

        cable_tester = hardware_manager.get_cable_tester()
        if not cable_tester:
            return

        serial_number = cable_record.get('serial_number')
        sku = cable_record.get('sku')

        # Keep cable info in body
        cable_info_panel = self.build_cable_info_panel(cable_record)
        self.ui.layout["body"].update(cable_info_panel)

        # Check calibration by doing a quick resistance read
        self.ui.layout["footer"].update(Panel("🔬 Checking calibration...", title="Testing"))
        self.ui.render()

        try:
            check_result = cable_tester.run_resistance_test()
            if not check_result.calibrated:
                # Need calibration - prompt user
                cal_result = self.run_calibration_prompt(operator, cable_record, cable_tester)
                if not cal_result:
                    return  # User cancelled
        except Exception:
            # If the check itself fails, try calibration anyway
            cal_result = self.run_calibration_prompt(operator, cable_record, cable_tester)
            if not cal_result:
                return

        # Now run the actual tests
        self.ui.layout["body"].update(cable_info_panel)
        self.ui.layout["footer"].update(Panel("🔬 Testing... Running continuity test", title="Testing"))
        self.ui.render()

        all_passed = True
        cont_status = "?"
        res_status = "?"
        resistance_adc = None
        calibration_adc = None

        # Run continuity test
        try:
            cont_result = cable_tester.run_continuity_test()
            if cont_result.passed:
                cont_status = "[green]PASS[/green]"
            else:
                cont_status = "[red]FAIL[/red]"
                all_passed = False
        except Exception as e:
            cont_status = "[yellow]ERROR[/yellow]"
            all_passed = False

        # Update footer and run resistance test
        self.ui.layout["footer"].update(Panel(f"🔬 Testing... CON: {cont_status} | Running resistance test", title="Testing"))
        self.ui.render()

        try:
            res_result = cable_tester.run_resistance_test()
            resistance_adc = res_result.adc_value
            calibration_adc = res_result.calibration_adc
            if res_result.passed:
                res_status = "[green]PASS[/green]"
            else:
                res_status = "[red]FAIL[/red]"
                all_passed = False
        except Exception as e:
            res_status = "[yellow]ERROR[/yellow]"
            all_passed = False

        # Always save test results to database
        saved_status = ""
        try:
            update_cable_test_results(serial_number, all_passed, resistance_adc=resistance_adc, calibration_adc=calibration_adc, operator=operator)
            saved_status = " | [green]Saved[/green]"
        except Exception as e:
            logger.error(f"Failed to save test results: {e}")
            saved_status = " | [red]Save failed[/red]"

        # Show final results in footer briefly
        if all_passed:
            result_text = f"✅ CON: {cont_status} | RES: {res_status}{saved_status}"
        else:
            result_text = f"❌ CON: {cont_status} | RES: {res_status}{saved_status}"

        self.ui.layout["footer"].update(Panel(result_text, title="Test Complete"))
        self.ui.render()
        time.sleep(1.5)

    def _run_xlr_cable_test(self, operator, cable_record):
        """Run XLR cable tests (continuity, shell bond, resistance) and save results

        Shell bond test only runs for touring series cables (studio XLR has coated shells).

        Args:
            operator: Operator ID
            cable_record: Cable record from database
        """
        from greenlight.hardware.interfaces import hardware_manager

        cable_tester = hardware_manager.get_cable_tester()
        if not cable_tester:
            return

        serial_number = cable_record.get('serial_number')
        series = cable_record.get('series', '')
        is_misc = cable_record.get('sku', '').endswith('-MISC')
        is_touring = series.startswith("Tour") and not is_misc

        # Keep cable info in body
        cable_info_panel = self.build_cable_info_panel(cable_record)
        self.ui.layout["body"].update(cable_info_panel)

        # Check XLR calibration
        self.ui.layout["footer"].update(Panel("🔬 Checking XLR calibration...", title="Testing"))
        self.ui.render()

        try:
            check_result = cable_tester.run_xlr_resistance_test()
            if not check_result.calibrated:
                cal_result = self.run_xlr_calibration_prompt(operator, cable_record, cable_tester)
                if not cal_result:
                    return
        except Exception:
            cal_result = self.run_xlr_calibration_prompt(operator, cable_record, cable_tester)
            if not cal_result:
                return

        # Run XLR continuity test
        self.ui.layout["body"].update(cable_info_panel)
        self.ui.layout["footer"].update(Panel("🔬 Testing... Running XLR continuity test", title="Testing"))
        self.ui.render()

        all_passed = True
        cont_status = "?"
        shell_status = "?"
        res_status = "?"
        resistance_adc = None
        calibration_adc = None

        try:
            cont_result = cable_tester.run_xlr_continuity_test()
            if cont_result.passed:
                cont_status = "[green]PASS[/green]"
            else:
                cont_status = "[red]FAIL[/red]"
                all_passed = False
        except Exception as e:
            cont_status = "[yellow]ERROR[/yellow]"
            all_passed = False

        # Run shell bond test (touring series only)
        if is_touring:
            progress = f"🔬 Testing... CON: {cont_status} | Running shell bond test"
            self.ui.layout["footer"].update(Panel(progress, title="Testing"))
            self.ui.render()

            try:
                shell_result = cable_tester.run_xlr_shell_test()
                if shell_result.passed:
                    shell_status = "[green]PASS[/green]"
                else:
                    shell_status = "[red]FAIL[/red]"
                    all_passed = False
            except Exception as e:
                shell_status = "[yellow]ERROR[/yellow]"
                all_passed = False

        # Run XLR resistance test
        if is_touring:
            progress = f"🔬 Testing... CON: {cont_status} | SHELL: {shell_status} | Running resistance test"
        else:
            progress = f"🔬 Testing... CON: {cont_status} | Running resistance test"
        self.ui.layout["footer"].update(Panel(progress, title="Testing"))
        self.ui.render()

        try:
            res_result = cable_tester.run_xlr_resistance_test()
            resistance_adc = res_result.pin2_adc  # Store pin2 ADC as primary
            calibration_adc = res_result.pin2_cal_adc
            if res_result.passed:
                res_status = "[green]PASS[/green]"
            else:
                res_status = "[red]FAIL[/red]"
                all_passed = False
        except Exception as e:
            res_status = "[yellow]ERROR[/yellow]"
            all_passed = False

        # Save test results
        saved_status = ""
        try:
            update_cable_test_results(serial_number, all_passed, resistance_adc=resistance_adc, calibration_adc=calibration_adc, operator=operator)
            saved_status = " | [green]Saved[/green]"
        except Exception as e:
            logger.error(f"Failed to save test results: {e}")
            saved_status = " | [red]Save failed[/red]"

        # Show final results
        if is_touring:
            summary = f"CON: {cont_status} | SHELL: {shell_status} | RES: {res_status}"
        else:
            summary = f"CON: {cont_status} | RES: {res_status}"

        icon = "✅" if all_passed else "❌"
        result_text = f"{icon} {summary}{saved_status}"

        self.ui.layout["footer"].update(Panel(result_text, title="Test Complete"))
        self.ui.render()
        time.sleep(1.5)

    def run_calibration_prompt(self, operator, cable_record, cable_tester):
        """Prompt user to insert reference cable and run calibration

        Args:
            operator: Operator ID
            cable_record: Cable record from database
            cable_tester: Cable tester instance

        Returns:
            True if calibration succeeded, False if user cancelled
        """
        cable_info_panel = self.build_cable_info_panel(cable_record)
        self.ui.layout["body"].update(cable_info_panel)
        self.ui.layout["footer"].update(Panel(
            "⚠️  [yellow]Tester not calibrated[/yellow]\n\n"
            "Insert the [bold]reference cable[/bold] (zero-ohm short) and press [green]Enter[/green] to calibrate\n"
            "Press [cyan]'q'[/cyan] to cancel",
            title="Calibration Required", border_style="yellow"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return False

        if choice == 'q':
            return False

        # Run calibration
        self.ui.layout["footer"].update(Panel("🔧 Calibrating...", title="Calibration"))
        self.ui.render()

        try:
            cal_result = cable_tester.calibrate()
            if cal_result.success:
                self.ui.layout["footer"].update(Panel(
                    f"✅ [green]Calibration complete[/green] (ADC: {cal_result.adc_value})\n\n"
                    "Now insert the [bold]cable to test[/bold] and press [green]Enter[/green]",
                    title="Calibration OK", border_style="green"
                ))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    return False
                return True
            else:
                self.ui.layout["footer"].update(Panel(
                    f"❌ [red]Calibration failed[/red]: {cal_result.error}\n\nPress enter to cancel",
                    title="Calibration Error", border_style="red"
                ))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    pass
                return False
        except Exception as e:
            logger.error(f"Calibration error: {e}")
            self.ui.layout["footer"].update(Panel(
                f"❌ [red]Calibration error[/red]: {e}\n\nPress enter to cancel",
                title="Calibration Error", border_style="red"
            ))
            self.ui.render()
            try:
                self.ui.console.input("")
            except KeyboardInterrupt:
                pass
            return False

    def run_xlr_calibration_prompt(self, operator, cable_record, cable_tester):
        """Prompt user to insert XLR reference cable and run calibration

        Args:
            operator: Operator ID
            cable_record: Cable record from database
            cable_tester: Cable tester instance

        Returns:
            True if calibration succeeded, False if user cancelled
        """
        cable_info_panel = self.build_cable_info_panel(cable_record)
        self.ui.layout["body"].update(cable_info_panel)
        self.ui.layout["footer"].update(Panel(
            "⚠️  [yellow]XLR tester not calibrated[/yellow]\n\n"
            "Insert the [bold]XLR reference cable[/bold] (zero-ohm short) and press [green]Enter[/green] to calibrate\n"
            "Press [cyan]'q'[/cyan] to cancel",
            title="XLR Calibration Required", border_style="yellow"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return False

        if choice == 'q':
            return False

        # Run XLR calibration
        self.ui.layout["footer"].update(Panel("🔧 Calibrating XLR...", title="XLR Calibration"))
        self.ui.render()

        try:
            cal_result = cable_tester.xlr_calibrate()
            if cal_result.success:
                self.ui.layout["footer"].update(Panel(
                    f"✅ [green]XLR calibration complete[/green]\n"
                    f"Pin 2 ADC: {cal_result.pin2_adc}  |  Pin 3 ADC: {cal_result.pin3_adc}\n\n"
                    "Now insert the [bold]cable to test[/bold] and press [green]Enter[/green]",
                    title="XLR Calibration OK", border_style="green"
                ))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    return False
                return True
            else:
                self.ui.layout["footer"].update(Panel(
                    f"❌ [red]XLR calibration failed[/red]: {cal_result.error}\n\nPress enter to cancel",
                    title="Calibration Error", border_style="red"
                ))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    pass
                return False
        except Exception as e:
            logger.error(f"XLR calibration error: {e}")
            self.ui.layout["footer"].update(Panel(
                f"❌ [red]XLR calibration error[/red]: {e}\n\nPress enter to cancel",
                title="Calibration Error", border_style="red"
            ))
            self.ui.render()
            try:
                self.ui.console.input("")
            except KeyboardInterrupt:
                pass
            return False

    @staticmethod
    def _calc_milliohms(adc_value, cal_adc):
        """Derive cable resistance in milliohms from ADC values.

        Uses the same formula as the Arduino firmware:
        sense voltage and cal voltage from 10-bit ADC, current through
        20Ω high-side sense resistor, resistance = delta_V / current.
        """
        sense_v = (adc_value / 1023.0) * 5.0
        cal_v = (cal_adc / 1023.0) * 5.0
        cal_current = (5.0 - cal_v) / 20.0
        if cal_current <= 0.001:
            return 0
        resistance = (sense_v - cal_v) / cal_current
        if resistance < 0:
            resistance = 0
        return int(resistance * 1000)

    def build_cable_info_panel(self, cable_record):
        """Build the cable information panel (extracted for reuse)"""
        serial_number = cable_record.get("serial_number", "N/A")
        sku = cable_record.get("sku", "N/A")
        series = cable_record.get("series", "N/A")
        length = cable_record.get("length", "N/A")
        color_pattern = cable_record.get("color_pattern", "N/A")
        connector_type = cable_record.get("connector_type", "N/A")
        resistance_adc = cable_record.get("resistance_adc")
        calibration_adc = cable_record.get("calibration_adc")
        test_passed = cable_record.get("test_passed")
        cable_operator = cable_record.get("operator", "N/A")
        test_timestamp = cable_record.get("test_timestamp")
        updated_timestamp = cable_record.get("updated_timestamp")

        # Format test results
        if test_passed is True:
            resistance_str = f"PASS (ADC: {resistance_adc}"
            if calibration_adc is not None and resistance_adc is not None:
                milliohms = self._calc_milliohms(resistance_adc, calibration_adc)
                resistance_str += f", {milliohms} mOhm"
            resistance_str += ")"
            test_status = "✅ PASS"
        elif test_passed is False:
            resistance_str = f"FAIL (ADC: {resistance_adc}"
            if calibration_adc is not None and resistance_adc is not None:
                milliohms = self._calc_milliohms(resistance_adc, calibration_adc)
                resistance_str += f", {milliohms} mOhm"
            resistance_str += ")"
            test_status = "❌ FAIL"
        else:
            resistance_str = "Not tested"
            test_status = "⏳ Not tested"

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
  Tested: {test_timestamp_str}
  Test Operator: {cable_operator if test_timestamp else 'N/A'}"""

        # Registration code (wholesale)
        registration_code = cable_record.get("registration_code")
        if registration_code:
            cable_info += f"""

[bold blue]Registration Code:[/bold blue] {registration_code}"""

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

    def show_menu(self, operator):
        """Show menu for additional options (inventory, orders, etc.)

        Returns:
            ScreenResult if user selects an option, None to return to scanning
        """
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "Additional Options\n\n"
            "[green]1.[/green] View Inventory - See available cables by type\n"
            "[green]2.[/green] Assign Cables - Assign cables to customer orders\n"
            "[green]3.[/green] Back to Scanning",
            title="Menu"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter choice (1-3) or press Enter to go back",
            title=""
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ").strip()

            if choice == "1":
                # View Inventory
                from greenlight.screens.inventory import SeriesSelectionScreen
                return ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, self.context)
            elif choice == "2":
                # Assign Cables - go to customer search
                from greenlight.screens.orders import CustomerLookupScreen
                return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, self.context)
            # Choice 3 or empty = back to scanning
            return None

        except KeyboardInterrupt:
            return None

    def show_not_found_with_register(self, operator, serial_number):
        """Show not found message with option to register the cable

        Returns:
            ScreenResult if user chooses to register, None to continue scanning
        """
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"❌ [bold red]Cable Not Found[/bold red]\n\n"
            f"Serial Number: [yellow]{serial_number}[/yellow]\n\n"
            f"This cable is not in the database.\n"
            f"Would you like to register it?",
            title="Not in Database", style="red"
        ))
        self.ui.layout["footer"].update(Panel(
            "[cyan]'r'[/cyan] = Register this cable | [cyan]Enter[/cyan] = Continue scanning",
            title="Options"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()

            if choice == 'r':
                # Go to register flow with this serial number pre-filled
                new_context = self.context.copy()
                new_context["selection_mode"] = "intake"
                new_context["prefill_serial"] = serial_number
                return ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, new_context)

            # Otherwise continue scanning
            return None

        except KeyboardInterrupt:
            return None


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

                # If there's only one connector type, skip the connector selection screen
                connector_options = get_distinct_connector_types(selected_series, selected_color, selected_length)
                if len(connector_options) == 1:
                    sku = find_cable_by_attributes(selected_series, selected_color, selected_length, connector_options[0])
                    if sku:
                        try:
                            cable_type = CableType()
                            cable_type.load(sku)
                            new_context["cable_type"] = cable_type
                            return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)
                        except ValueError:
                            pass  # Fall through to connector selection screen

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


# ============================================================================
# Additional Cable Screens (from new_screens.py)
# ============================================================================


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
        max_desc_len = 90
        prefill_text = None

        try:
            while True:
                if prefill_text:
                    self.ui.layout["footer"].update(Panel(
                        f"[red]Too long ({len(prefill_text)}/{max_desc_len} chars) — please shorten:[/red]",
                        title="Description"
                    ))
                else:
                    self.ui.layout["footer"].update(Panel(
                        f"Enter description (max {max_desc_len} chars) or 'q' to cancel",
                        title="Description"
                    ))
                self.ui.render()

                # Pre-fill input with previous too-long text so user can edit in place
                if prefill_text:
                    readline.set_startup_hook(lambda: readline.insert_text(prefill_text))
                else:
                    readline.set_startup_hook(None)

                try:
                    description = self.ui.console.input("Description: ").strip()
                finally:
                    readline.set_startup_hook(None)

                if description.lower() == 'q' or not description:
                    return None

                if len(description) <= max_desc_len:
                    return description

                prefill_text = description
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
        self._pending_serial = None

        while True:
            # Check if we have a pending serial from offer_print_label
            if self._pending_serial:
                serial_number = self._pending_serial
                self._pending_serial = None
            else:
                # Clear console before rendering to avoid layout corruption
                self.ui.console.clear()

                # Show current status
                self.ui.header(operator)

                scan_info = (
                    f"[bold cyan]Cable Type:[/bold cyan] {cable_type.name()}\n"
                    f"[bold cyan]SKU:[/bold cyan] {cable_type.sku}\n"
                )
                if cable_description:
                    scan_info += f"[bold cyan]Description:[/bold cyan] {cable_description}\n"
                scan_info += f"\n[bold yellow]Scanned:[/bold yellow] {scanned_count} cable{'s' if scanned_count != 1 else ''}"
                if scanned_serials:
                    recent = scanned_serials[-5:]
                    scan_info += f"\n[dim]Recent: {', '.join(recent)}[/dim]"

                self.ui.layout["body"].update(Panel(
                    scan_info,
                    title="📦 Register Cables",
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

                # Show success and ask what to do next
                next_action = self.offer_print_label(operator, cable_type, saved_serial, custom_length, cable_description)
                if next_action == 'quit':
                    break
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

        # Go back to main scan screen
        return ScreenResult(NavigationAction.REPLACE, ScanCableLookupScreen, self.context)

    def offer_print_label(self, operator, cable_type, serial_number, custom_length=None, cable_description=None):
        """Show cable info after registration and prompt for actions.

        Displays the full cable info screen (same as scan-lookup) with all
        available options: test, print label, edit description, scan next.
        Loops back to the same screen after each action so updated info is shown.

        Args:
            operator: Operator ID
            cable_type: CableType object
            serial_number: Registered serial number
            custom_length: Optional custom length for MISC cables
            cable_description: Optional description for MISC cables

        Returns:
            'continue' to register another cable, 'quit' to go back
        """
        from greenlight.hardware.interfaces import hardware_manager
        from greenlight.db import get_audio_cable

        lookup_screen = ScanCableLookupScreen(self.ui, self.context)

        try:
            while True:
                # Reload cable record each iteration to show updated info
                cable_record = get_audio_cable(serial_number)

                # Check hardware availability
                cable_tester = hardware_manager.get_cable_tester()
                tester_available = cable_tester and cable_tester.is_ready() if cable_tester else False
                label_printer = hardware_manager.get_label_printer()
                printer_available = label_printer and label_printer.is_ready() if label_printer else False
                cable_tested = cable_record.get('test_passed') is True if cable_record else False
                is_misc = cable_record.get('sku', '').endswith('-MISC') if cable_record else False

                self.ui.console.clear()
                self.ui.header(operator)

                if cable_record:
                    cable_info_panel = lookup_screen.build_cable_info_panel(cable_record)
                    self.ui.layout["body"].update(cable_info_panel)
                else:
                    self.ui.layout["body"].update(Panel(
                        f"[bold green]✅ Cable Registered[/bold green]\n\n"
                        f"Serial Number: {serial_number}\n"
                        f"SKU: {cable_type.sku}",
                        title="Registration Complete",
                        border_style="green"
                    ))

                # Build footer with all available options (same as show_cable_info_with_actions)
                footer_options = []
                if tester_available:
                    footer_options.append("[cyan]'t'[/cyan] = Test cable")
                if printer_available and cable_tested:
                    footer_options.append("[cyan]'p'[/cyan] = Print label")
                if is_misc:
                    footer_options.append("[cyan]'d'[/cyan] = Edit description")
                footer_options.append("[bold green]Scan[/bold green] next cable")
                footer_options.append("[cyan]'q'[/cyan] = Go back")

                self.ui.layout["footer"].update(Panel(
                    " | ".join(footer_options),
                    title="Options"
                ))
                self.ui.render()

                choice = self.get_serial_number_scan_or_manual()
                if not choice:
                    return 'quit'
                choice_lower = choice.strip().lower()

                if choice_lower == 't' and tester_available:
                    cable_record = get_audio_cable(serial_number)
                    if cable_record:
                        lookup_screen.run_cable_test(operator, cable_record)
                    # Loop back to show updated cable info
                    continue
                elif choice_lower == 'p' and printer_available and cable_tested:
                    if cable_record:
                        lookup_screen.print_label_for_cable(operator, cable_record)
                    continue
                elif choice_lower == 'd' and is_misc:
                    if cable_record:
                        lookup_screen.edit_cable_description(operator, cable_record)
                    continue
                elif choice_lower == 'q':
                    return 'quit'
                else:
                    # Input is a new serial number scan
                    self._pending_serial = choice.strip().upper()
                    return 'continue'

        except KeyboardInterrupt:
            return 'quit'

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
            'serial_number': serial_number,
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
        resistance_adc = cable_record.get("resistance_adc")
        calibration_adc = cable_record.get("calibration_adc")
        test_passed = cable_record.get("test_passed")
        cable_operator = cable_record.get("operator", "N/A")
        test_timestamp = cable_record.get("test_timestamp")
        updated_timestamp = cable_record.get("updated_timestamp")

        # Format test results
        if test_passed is True:
            resistance_str = f"PASS (ADC: {resistance_adc}"
            if calibration_adc is not None and resistance_adc is not None:
                milliohms = self._calc_milliohms(resistance_adc, calibration_adc)
                resistance_str += f", {milliohms} mOhm"
            resistance_str += ")"
            test_status = "✅ PASS"
        elif test_passed is False:
            resistance_str = f"FAIL (ADC: {resistance_adc}"
            if calibration_adc is not None and resistance_adc is not None:
                milliohms = self._calc_milliohms(resistance_adc, calibration_adc)
                resistance_str += f", {milliohms} mOhm"
            resistance_str += ")"
            test_status = "❌ FAIL"
        else:
            resistance_str = "Not tested"
            test_status = "⏳ Not tested"

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
  Tested: {test_timestamp_str}
  Test Operator: {cable_operator if test_timestamp else 'N/A'}"""

        # Registration code (wholesale)
        registration_code = cable_record.get("registration_code")
        if registration_code:
            cable_info += f"""

[bold blue]Registration Code:[/bold blue] {registration_code}"""

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


