from rich.panel import Panel
import logging

logger = logging.getLogger(__name__)
import sys
import termios
import tty
import readline
import re

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.config import APP_NAME, EXIT_MESSAGE
from greenlight.cable import (
    CableType, get_all_skus, filter_skus, get_distinct_series,
    get_distinct_color_patterns, get_distinct_lengths, get_distinct_connector_types,
    resolve_catalog_variant,
)
from greenlight.db import get_audio_cable, register_scanned_cable, format_serial_number, update_cable_test_results
from rich.table import Table
import time


def _calc_milliohms(adc_value, cal_adc):
    """Derive cable resistance in milliohms from ADC values.

    Uses the same formula as the Arduino firmware:
    sense voltage and cal voltage from 10-bit ADC, current through
    20Ohm high-side sense resistor, resistance = delta_V / current.
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


class CableScreenBase(Screen):
    """Base class for cable screens with shared cable methods"""

    def get_serial_number_scan_or_manual(self):
        """Get serial number via barcode scanner using evdev or manual keyboard input.

        Does NOT clear the scanner queue internally — callers should clear
        at the start of their main loop if needed.
        """
        from greenlight.hardware.barcode_scanner import get_scanner
        import select
        import sys

        scanner = get_scanner()

        # Try to initialize and start scanner
        scanner_available = False
        if scanner.initialize():
            scanner.start_scanning()
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

    def build_cable_info_panel(self, cable_record):
        """Build the cable information panel in two-column layout"""
        serial_number = cable_record.get("serial_number", "N/A")
        variant_sku = cable_record.get("variant_sku", "N/A")
        series = cable_record.get("series", "N/A")
        length = cable_record.get("length", "N/A")
        pattern_name = cable_record.get("pattern_name")
        connector_display = cable_record.get("connector_display")
        resistance_adc = cable_record.get("resistance_adc")
        calibration_adc = cable_record.get("calibration_adc")
        resistance_adc_p3 = cable_record.get("resistance_adc_p3")
        calibration_adc_p3 = cable_record.get("calibration_adc_p3")
        test_passed = cable_record.get("test_passed")
        cable_operator = cable_record.get("operator", "N/A")
        test_timestamp = cable_record.get("test_timestamp")
        updated_timestamp = cable_record.get("updated_timestamp")
        is_xlr = 'XLR' in (connector_display or '').upper() or 'vocal' in (series or '').lower()

        # Format test results
        if test_passed is True:
            test_status = "✅ PASS"
        elif test_passed is False:
            test_status = "❌ FAIL"
        else:
            test_status = "⏳ Not tested"

        # Format resistance display
        if test_passed is not None and resistance_adc is not None:
            pass_fail = "PASS" if test_passed else "FAIL"
            if is_xlr and resistance_adc_p3 is not None:
                p2_detail = f"ADC:{resistance_adc}"
                if calibration_adc is not None:
                    p2_detail += f"/{_calc_milliohms(resistance_adc, calibration_adc)}mOhm"
                p3_detail = f"ADC:{resistance_adc_p3}"
                if calibration_adc_p3 is not None:
                    p3_detail += f"/{_calc_milliohms(resistance_adc_p3, calibration_adc_p3)}mOhm"
                resistance_str = f"{pass_fail} (P2: {p2_detail}, P3: {p3_detail})"
            else:
                resistance_str = f"{pass_fail} (ADC: {resistance_adc}"
                if calibration_adc is not None:
                    milliohms = _calc_milliohms(resistance_adc, calibration_adc)
                    resistance_str += f", {milliohms} mOhm"
                resistance_str += ")"
        else:
            resistance_str = "Not tested"

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

        # -- Left column: cable identity --
        left = f"""[bold yellow]Serial:[/bold yellow] {serial_number}
[bold yellow]SKU:[/bold yellow] {variant_sku}
[bold yellow]Registered:[/bold yellow] {updated_timestamp_str}

[bold cyan]Cable Details:[/bold cyan]
  Series: {series}
  Length: {length} ft"""

        # pattern_name is catalog-only (None for MISC/LTD); connector_display
        # is set for any known prefix.
        if pattern_name:
            left += f"\n  Color: {pattern_name}"
        if connector_display:
            left += f"\n  Connector: {connector_display}"

        kind = cable_record.get("kind")
        description = cable_record.get("description")
        if kind in ('misc', 'ltd') and description:
            label = "Edition" if kind == 'ltd' else "Description"
            color = "[bold magenta]" if kind == 'ltd' else ""
            left += f"\n  {color}{label}:[/bold magenta] {description}" if color else f"\n  {label}: {description}"

        registration_code = cable_record.get("registration_code")
        if registration_code:
            left += f"\n\n[bold blue]Reg Code:[/bold blue] {registration_code}"

        # -- Right column: test results & assignment --
        test_notes = cable_record.get("notes")
        right = f"[bold green]Test Status:[/bold green] {test_status}"
        if test_passed is False and test_notes:
            right += f"\n  [bold red]Failure:[/bold red] {test_notes}"
        right += f"""
  Resistance: {resistance_str}
  Tested: {test_timestamp_str}
  Operator: {cable_operator if test_timestamp else 'N/A'}"""

        # Customer assignment
        customer_gid = cable_record.get("shopify_gid")
        if customer_gid:
            from greenlight import shopify_client
            customer_numeric_id = customer_gid.split('/')[-1]
            customer = shopify_client.get_customer_by_id(customer_numeric_id)

            if customer:
                customer_name = customer.get("displayName") or "(no name)"
                customer_email = customer.get("email")
                address = customer.get("defaultAddress")
                customer_phone = customer.get("phone") or (address.get("phone") if address else None)
                band_company = shopify_client.get_band_company(customer)

                assigned_lines = [f"  {customer_name}"]
                if band_company:
                    assigned_lines.append(f"  [magenta]{band_company}[/magenta]")
                if customer_email:
                    assigned_lines.append(f"  {customer_email}")
                if customer_phone:
                    assigned_lines.append(f"  {customer_phone}")

                right += "\n\n[bold magenta]✅ Assigned To:[/bold magenta]\n" + "\n".join(assigned_lines)
            else:
                right += f"""

[bold magenta]Assigned To:[/bold magenta]
  [yellow]ID: {customer_gid}[/yellow]"""
        else:
            right += """

[bold magenta]Assignment:[/bold magenta]
  [yellow]⏳ Not assigned[/yellow]"""

        # Two-column layout using Table
        layout_table = Table(show_header=False, show_edge=False, box=None, padding=(0, 2), expand=True)
        layout_table.add_column(ratio=1)
        layout_table.add_column(ratio=1)
        layout_table.add_row(left, right)

        return Panel(layout_table, title="📋 Cable Information", style="cyan")

    def run_cable_test(self, operator, cable_record):
        """Run cable tests and save results. Routes to TS or XLR test flow.

        Args:
            operator: Operator ID
            cable_record: Cable record from database
        """
        # connector_display can be None for unknown prefixes; fall back to series check.
        connector_display = (cable_record.get('connector_display') or '').upper()
        series = (cable_record.get('series') or '').lower()
        if 'XLR' in connector_display or 'vocal' in series:
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
        sku = cable_record.get('variant_sku')

        # Keep cable info in body
        cable_info_panel = self.build_cable_info_panel(cable_record)
        self.ui.layout["body"].update(cable_info_panel)

        # Check calibration by doing a quick resistance read
        self.ui.layout["footer"].update(Panel("🔬 Checking calibration...", title="Testing"))
        self.ui.render()
        try:
            check_result = cable_tester.run_resistance_test()
            if not check_result.calibrated:
                cal_result = self.run_calibration_prompt(operator, cable_record, cable_tester)
                if not cal_result:
                    return  # User cancelled
        except Exception:
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
        failure_reasons = []

        # Run continuity test
        cont_reason = None
        try:
            cont_result = cable_tester.run_continuity_test()
            if cont_result.passed:
                cont_status = "[green]PASS[/green]"
            else:
                cont_reason = cont_result.reason
                reason_display = {
                    'REVERSED': 'Reversed polarity',
                    'SHORT': 'Tip/sleeve shorted',
                    'NO_CABLE': 'No cable detected',
                    'TIP_OPEN': 'Tip open',
                    'SLEEVE_OPEN': 'Sleeve open',
                }.get(cont_reason, cont_reason or 'Unknown')
                cont_status = f"[red]FAIL ({reason_display})[/red]"
                failure_reasons.append(f"CON: {reason_display}")
                all_passed = False
        except Exception as e:
            cont_status = "[yellow]ERROR[/yellow]"
            failure_reasons.append(f"CON: Error")
            all_passed = False

        # Only run resistance test if continuity passed
        if all_passed:
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
                    failure_reasons.append("RES: Fail")
                    all_passed = False
            except Exception as e:
                res_status = "[yellow]ERROR[/yellow]"
                failure_reasons.append("RES: Error")
                all_passed = False
        else:
            res_status = "[dim]SKIP[/dim]"

        # Build notes from failure reasons (None if passed clears old notes)
        test_notes = "; ".join(failure_reasons) if failure_reasons else None

        # Always save test results to database
        saved_status = ""
        try:
            update_cable_test_results(serial_number, all_passed, resistance_adc=resistance_adc, calibration_adc=calibration_adc, operator=operator, notes=test_notes)
            saved_status = " | [green]Saved[/green]"
        except Exception as e:
            logger.error(f"Failed to save test results: {e}")
            saved_status = " | [red]Save failed[/red]"

        # Set Shopify inventory to match Postgres available count (best-effort; reconcile tool catches drift).
        # LTD cables aren't sold via Shopify so they have no product to sync.
        kind = cable_record.get('kind')
        if all_passed and kind != 'ltd':
            try:
                from greenlight.db import get_available_count_for_sku
                variant_sku = cable_record['variant_sku']
                count = get_available_count_for_sku(variant_sku)
                if kind == 'misc':
                    from greenlight.shopify_client import ensure_misc_shopify_product
                    success, err = ensure_misc_shopify_product(cable_record, quantity=count)
                else:
                    from greenlight.shopify_client import set_inventory_for_sku
                    success, err = set_inventory_for_sku(variant_sku, count)
                if success:
                    saved_status += f" | [green]Shopify={count}[/green]"
                else:
                    logger.warning(f"Shopify inventory update failed for {serial_number}: {err}")
                    saved_status += f" | [yellow]Shopify failed: {err}[/yellow]"
            except Exception as e:
                logger.error(f"Shopify inventory error: {e}")
                saved_status += f" | [yellow]Shopify error: {e}[/yellow]"

        # Show final results - refresh body with updated record from DB
        result_icon = "✅" if all_passed else "❌"
        result_text = f"{result_icon} CON: {cont_status} | RES: {res_status}{saved_status}"

        updated_record = get_audio_cable(serial_number)
        if updated_record:
            self.ui.layout["body"].update(self.build_cable_info_panel(updated_record))
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
        series = cable_record.get('series') or ''
        is_misc = cable_record.get('kind') == 'misc'
        is_ltd = cable_record.get('kind') == 'ltd'
        is_touring = series.startswith("Tour") and not is_misc

        # Keep cable info in body
        cable_info_panel = self.build_cable_info_panel(cable_record)
        self.ui.layout["body"].update(cable_info_panel)

        # Check XLR calibration by doing a quick resistance read
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
        resistance_adc_p3 = None
        calibration_adc_p3 = None
        failure_reasons = []

        try:
            cont_result = cable_tester.run_xlr_continuity_test()
            if cont_result.passed:
                cont_status = "[green]PASS[/green]"
            else:
                cont_reason = cont_result.reason or 'Unknown'
                # Parse XLR reasons: P1_OPEN, P2_P3_SHORT, NO_CABLE, etc.
                reason_parts = cont_reason.split(',')
                friendly = []
                for part in reason_parts:
                    part = part.strip()
                    if part == 'NO_CABLE':
                        friendly.append('No cable')
                    elif part.endswith('_OPEN'):
                        pin = part.replace('_OPEN', '')
                        friendly.append(f'{pin} open')
                    elif '_SHORT' in part:
                        friendly.append(part.replace('_', '/').replace('/SHORT', ' short'))
                    else:
                        friendly.append(part)
                cont_status = f"[red]FAIL ({', '.join(friendly)})[/red]"
                failure_reasons.append(f"CON: {', '.join(friendly)}")
                all_passed = False
        except Exception as e:
            cont_status = "[yellow]ERROR[/yellow]"
            failure_reasons.append("CON: Error")
            all_passed = False

        # Run shell bond test (touring series only, skip if continuity failed)
        if is_touring and all_passed:
            progress = f"🔬 Testing... CON: {cont_status} | Running shell bond test"
            self.ui.layout["footer"].update(Panel(progress, title="Testing"))
            self.ui.render()

            try:
                shell_result = cable_tester.run_xlr_shell_test()
                if shell_result.passed:
                    shell_status = "[green]PASS[/green]"
                else:
                    shell_reason = shell_result.reason or 'Unknown'
                    reason_parts = shell_reason.split(',')
                    friendly = []
                    for part in reason_parts:
                        part = part.strip()
                        if part == 'NEAR_SHELL_OPEN':
                            friendly.append('Near shell open')
                        elif part == 'FAR_SHELL_OPEN':
                            friendly.append('Far shell open')
                        elif 'SHORT' in part:
                            friendly.append(part.replace('_', '/').replace('/SHORT', ' short'))
                        else:
                            friendly.append(part)
                    shell_status = f"[red]FAIL ({', '.join(friendly)})[/red]"
                    failure_reasons.append(f"SHELL: {', '.join(friendly)}")
                    all_passed = False
            except Exception as e:
                shell_status = "[yellow]ERROR[/yellow]"
                failure_reasons.append("SHELL: Error")
                all_passed = False
        elif is_touring:
            shell_status = "[dim]SKIP[/dim]"

        # Only run resistance test if continuity passed
        if all_passed:
            if is_touring:
                progress = f"🔬 Testing... CON: {cont_status} | SHELL: {shell_status} | Running resistance test"
            else:
                progress = f"🔬 Testing... CON: {cont_status} | Running resistance test"
            self.ui.layout["footer"].update(Panel(progress, title="Testing"))
            self.ui.render()

            try:
                res_result = cable_tester.run_xlr_resistance_test()
                resistance_adc = res_result.pin2_adc
                calibration_adc = res_result.pin2_cal_adc
                resistance_adc_p3 = res_result.pin3_adc
                calibration_adc_p3 = res_result.pin3_cal_adc
                if res_result.passed:
                    res_status = "[green]PASS[/green]"
                else:
                    res_status = "[red]FAIL[/red]"
                    failure_reasons.append("RES: Fail")
                    all_passed = False
            except Exception as e:
                res_status = "[yellow]ERROR[/yellow]"
                failure_reasons.append("RES: Error")
                all_passed = False
        else:
            res_status = "[dim]SKIP[/dim]"

        # Build notes from failure reasons (None if passed clears old notes)
        test_notes = "; ".join(failure_reasons) if failure_reasons else None

        # Save test results
        saved_status = ""
        try:
            update_cable_test_results(serial_number, all_passed, resistance_adc=resistance_adc, calibration_adc=calibration_adc,
                                     resistance_adc_p3=resistance_adc_p3, calibration_adc_p3=calibration_adc_p3, operator=operator, notes=test_notes)
            saved_status = " | [green]Saved[/green]"
        except Exception as e:
            logger.error(f"Failed to save test results: {e}")
            saved_status = " | [red]Save failed[/red]"

        # Set Shopify inventory to match Postgres available count (best-effort; reconcile tool catches drift).
        # LTD cables aren't sold via Shopify so they have no product to sync.
        if all_passed and not is_ltd:
            try:
                from greenlight.db import get_available_count_for_sku
                variant_sku = cable_record['variant_sku']
                count = get_available_count_for_sku(variant_sku)
                if is_misc:
                    from greenlight.shopify_client import ensure_misc_shopify_product
                    success, err = ensure_misc_shopify_product(cable_record, quantity=count)
                else:
                    from greenlight.shopify_client import set_inventory_for_sku
                    success, err = set_inventory_for_sku(variant_sku, count)
                if success:
                    saved_status += f" | [green]Shopify={count}[/green]"
                else:
                    logger.warning(f"Shopify inventory update failed for {serial_number}: {err}")
                    saved_status += f" | [yellow]Shopify failed: {err}[/yellow]"
            except Exception as e:
                logger.error(f"Shopify inventory error: {e}")
                saved_status += f" | [yellow]Shopify error: {e}[/yellow]"

        # Show final results - refresh body with updated record from DB
        if is_touring:
            summary = f"CON: {cont_status} | SHELL: {shell_status} | RES: {res_status}"
        else:
            summary = f"CON: {cont_status} | RES: {res_status}"

        icon = "✅" if all_passed else "❌"
        result_text = f"{icon} {summary}{saved_status}"

        updated_record = get_audio_cable(serial_number)
        if updated_record:
            self.ui.layout["body"].update(self.build_cable_info_panel(updated_record))
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

    def run_manual_calibration(self, operator):
        """Run manual TS and XLR calibration from the main scan screen"""
        from greenlight.hardware.interfaces import hardware_manager

        cable_tester = hardware_manager.get_cable_tester()
        if not cable_tester or not cable_tester.connected:
            return

        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "[bold cyan]Cable Tester Calibration[/bold cyan]\n\n"
            "Insert the [bold]TS reference cable[/bold] (zero-ohm short)\n"
            "into the test jacks and press [green]Enter[/green] to calibrate.\n\n"
            "[dim]This calibrates the TS (1/4\") tester.[/dim]",
            title="TS Calibration"
        ))
        self.ui.layout["footer"].update(Panel(
            "[green]Enter[/green] = Calibrate TS | [cyan]'s'[/cyan] = Skip to XLR | [cyan]'q'[/cyan] = Cancel",
            title=""
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return

        if choice == 'q':
            return

        ts_result = None
        if choice != 's':
            # Run TS calibration
            self.ui.layout["footer"].update(Panel("🔧 Calibrating TS...", title="Calibrating"))
            self.ui.render()

            try:
                ts_result = cable_tester.calibrate()
                if ts_result.success:
                    ts_msg = f"✅ TS calibration OK (ADC: {ts_result.adc_value})"
                else:
                    ts_msg = f"❌ TS calibration failed: {ts_result.error}"
            except Exception as e:
                ts_msg = f"❌ TS calibration error: {e}"
                logger.error(f"TS calibration error: {e}")

            self.ui.layout["body"].update(Panel(
                f"{ts_msg}\n\n"
                "Now insert the [bold]XLR reference cable[/bold] (zero-ohm short)\n"
                "and press [green]Enter[/green] to calibrate XLR.\n\n"
                "[dim]Or press 'q' to finish.[/dim]",
                title="XLR Calibration"
            ))
            self.ui.layout["footer"].update(Panel(
                "[green]Enter[/green] = Calibrate XLR | [cyan]'q'[/cyan] = Done",
                title=""
            ))
            self.ui.render()
        else:
            # Skipped TS, go straight to XLR
            self.ui.layout["body"].update(Panel(
                "Insert the [bold]XLR reference cable[/bold] (zero-ohm short)\n"
                "into the test jacks and press [green]Enter[/green] to calibrate.\n\n"
                "[dim]This calibrates the XLR tester.[/dim]",
                title="XLR Calibration"
            ))
            self.ui.layout["footer"].update(Panel(
                "[green]Enter[/green] = Calibrate XLR | [cyan]'q'[/cyan] = Done",
                title=""
            ))
            self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return

        if choice == 'q':
            return

        # Run XLR calibration
        self.ui.layout["footer"].update(Panel("🔧 Calibrating XLR...", title="Calibrating"))
        self.ui.render()

        try:
            xlr_result = cable_tester.xlr_calibrate()
            if xlr_result.success:
                xlr_msg = f"✅ XLR calibration OK (P2 ADC: {xlr_result.pin2_adc}, P3 ADC: {xlr_result.pin3_adc})"
            else:
                xlr_msg = f"❌ XLR calibration failed: {xlr_result.error}"
        except Exception as e:
            xlr_msg = f"❌ XLR calibration error: {e}"
            logger.error(f"XLR calibration error: {e}")

        # Show final results
        results = []
        if ts_result:
            if ts_result.success:
                results.append(f"✅ TS: ADC {ts_result.adc_value}")
            else:
                results.append(f"❌ TS: {ts_result.error}")
        results.append(xlr_msg)

        self.ui.layout["body"].update(Panel(
            "\n".join(results),
            title="Calibration Complete", border_style="green"
        ))
        self.ui.layout["footer"].update(Panel("Press [green]Enter[/green] to continue", title=""))
        self.ui.render()

        try:
            self.ui.console.input("")
        except KeyboardInterrupt:
            pass

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
        variant_sku = cable_record.get('variant_sku')
        series = cable_record.get('series')
        length = cable_record.get('length')
        pattern_name = cable_record.get('pattern_name')
        connector_display = cable_record.get('connector_display')
        description = cable_record.get('description')
        test_passed = cable_record.get('test_passed')
        cable_operator = cable_record.get('operator')

        # Prepare label data — printer expects sku/color_pattern/connector_type
        # as its fixed input contract. Source from the canonical resolver-derived
        # cable_record fields above.
        label_data = {
            'serial_number': serial_number,
            'series': series,
            'length': length,
            'color_pattern': pattern_name,
            'connector_type': connector_display,
            'sku': variant_sku,
        }
        if description:
            label_data['description'] = description

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

    def print_barcode_for_cable(self, operator, cable_record):
        """Print a barcode label with the cable's serial number.

        Args:
            operator: Operator ID
            cable_record: Cable record from database
        """
        from greenlight.hardware.interfaces import hardware_manager, PrintJob

        label_printer = hardware_manager.get_label_printer()
        if not label_printer:
            return

        serial_number = cable_record.get('serial_number', '')
        sku = cable_record.get('variant_sku') or cable_record.get('sku_group') or ''
        series = cable_record.get('series', '')
        length = cable_record.get('length', '')
        color_pattern = cable_record.get('pattern_name') or ''
        connector_type = cable_record.get('connector_display') or ''

        print_job = PrintJob(
            template="barcode_label",
            data={
                'serial_number': serial_number,
                'sku': sku,
                'series': series,
                'length': length,
                'color_pattern': color_pattern,
                'connector_type': connector_type,
            },
            quantity=1,
        )
        label_printer.print_labels(print_job)

    def print_registration_label(self, operator, cable_record):
        """Print a registration label for a cable that already has a registration code.

        Args:
            operator: Operator ID
            cable_record: Cable record from database (must have registration_code)
        """
        from greenlight.hardware.interfaces import hardware_manager, PrintJob
        from greenlight.registration import generate_registration_url

        label_printer = hardware_manager.get_label_printer()
        if not label_printer:
            return

        reg_code = cable_record.get('registration_code', '')
        if not reg_code:
            return

        reg_url = generate_registration_url(reg_code)

        print_job = PrintJob(
            template="registration_label",
            data={
                'registration_code': reg_code,
                'registration_url': reg_url,
                'serial_number': cable_record.get('serial_number', ''),
                'sku': cable_record.get('sku', ''),
            },
            quantity=1,
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
        is_misc_variant = cable_record.get('kind') == 'misc'

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
                if is_misc_variant:
                    prompt_text += "[bold yellow]Warning: This will change the description for ALL cables of this MISC variant.[/bold yellow]\n\n"
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
                        # Update Shopify description for MISC variants (catalog SKUs use
                        # their own marketing copy from the product line, don't overwrite)
                        if updated.get('kind') == 'misc' and updated.get('variant_sku'):
                            from greenlight.shopify_client import update_shopify_product_description
                            success, err = update_shopify_product_description(updated['variant_sku'], new_desc)
                            if not success:
                                logger.warning(f"Shopify description update failed: {err}")
                        return updated
                return cable_record
        except KeyboardInterrupt:
            return cable_record

    def _unassign_cable(self, operator, cable_record):
        """Prompt for confirmation and unassign a cable from its customer/order."""
        from greenlight import shopify_client, db as db_mod

        serial = cable_record['serial_number']
        customer_gid = cable_record.get('shopify_gid', '')

        # Look up customer name for the confirmation prompt
        customer_name = "unknown customer"
        try:
            if customer_gid:
                customer_numeric_id = customer_gid.split('/')[-1]
                customer = shopify_client.get_customer_by_id(customer_numeric_id)
                if customer:
                    customer_name = customer.get('displayName') or customer_name
        except:
            pass

        has_order = bool(cable_record.get('shopify_order_gid'))
        order_note = "\n[yellow]This cable is also assigned to an order — both will be cleared.[/yellow]" if has_order else ""

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[yellow]Unassign cable {serial}?[/yellow]\n\n"
            f"Currently assigned to: [cyan]{customer_name}[/cyan]"
            f"{order_note}\n\n"
            f"This will return the cable to available inventory.",
            title="Unassign Cable"
        ))
        self.ui.layout["footer"].update(Panel(
            "[green]y[/green] = Confirm unassign | [cyan]n[/cyan] = Cancel",
            title="Confirm?"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return

        if choice not in ('y', 'yes'):
            return

        result = db_mod.unassign_cable(serial)
        if result.get('success'):
            self.ui.layout["body"].update(Panel(
                f"[bold green]Cable {serial} unassigned and returned to inventory.[/bold green]\n\n"
                f"[dim]Press enter to continue[/dim]",
                title="Unassigned", style="green"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"[red]Error: {result.get('message', 'Unknown error')}[/red]\n\n"
                f"[dim]Press enter to continue[/dim]",
                title="Error"
            ))
        self.ui.layout["footer"].update(Panel("", title=""))
        self.ui.render()
        self.ui.console.input()

    def cable_action_loop(self, operator, cable_record, mode='lookup'):
        """Show cable info + action menu. Loops until quit or new scan.

        mode='lookup': shows assign + re-register options
        mode='intake': no assign/re-register options

        Returns:
            {'action': 'quit'}
            {'action': 'scan', 'serial': '...'}
            {'action': 'navigate', 'screen_result': ScreenResult}
        """
        from greenlight.hardware.interfaces import hardware_manager
        from greenlight.db import get_audio_cable

        while True:
            # Reload cable record each iteration to show updated info
            cable_record = get_audio_cable(cable_record['serial_number']) or cable_record

            # Display cable info
            self.ui.console.clear()
            self.ui.header(operator)
            cable_info_panel = self.build_cable_info_panel(cable_record)
            self.ui.layout["body"].update(cable_info_panel)

            # Check hardware availability
            cable_tester = hardware_manager.get_cable_tester()
            tester_available = cable_tester.connected if cable_tester else False
            label_printer = hardware_manager.get_label_printer()
            printer_available = label_printer.is_ready() if label_printer else False

            cable_tested = cable_record.get('test_passed') is True
            is_misc = cable_record.get('kind') == 'misc'
            is_assigned = bool(cable_record.get('shopify_gid'))

            # Build footer options based on mode and hardware
            footer_options = []
            if tester_available:
                footer_options.append("[cyan]'t'[/cyan] = Test cable")
            if mode == 'lookup' and not is_assigned:
                footer_options.append("[cyan]'a'[/cyan] = Assign cable")
            if mode == 'lookup' and is_assigned:
                footer_options.append("[cyan]'u'[/cyan] = Unassign cable")
            if printer_available and cable_tested:
                footer_options.append("[cyan]'p'[/cyan] = Print label")
            if printer_available:
                footer_options.append("[cyan]'b'[/cyan] = Print barcode")
            has_reg_code = bool(cable_record.get('registration_code'))
            if printer_available and has_reg_code:
                footer_options.append("[cyan]'l'[/cyan] = Print reg label")
            if is_misc:
                footer_options.append("[cyan]'d'[/cyan] = Edit description")
            if mode == 'lookup' and not is_assigned:
                footer_options.append("[cyan]'e'[/cyan] = Re-register")
            footer_options.append("[bold green]Scan[/bold green] next cable")
            footer_options.append("[cyan]'q'[/cyan] = Back")

            self.ui.layout["footer"].update(Panel(" | ".join(footer_options), title="Options"))
            self.ui.render()

            try:
                choice = self.get_serial_number_scan_or_manual()
                if not choice:
                    return {'action': 'quit'}
                choice_lower = choice.strip().lower()

                if choice_lower == 't' and tester_available:
                    self.run_cable_test(operator, cable_record)
                    # Auto-print label if test passed and printer available
                    updated = get_audio_cable(cable_record['serial_number'])
                    if updated and updated.get('test_passed') is True and printer_available:
                        self.print_label_for_cable(operator, updated)
                    # Loop to show updated info
                    continue

                elif choice_lower == 'a' and mode == 'lookup' and not is_assigned:
                    from greenlight.screens.orders import CustomerLookupScreen
                    # Set return flag on our own context so ScanCableLookupScreen
                    # re-enters cable_action_loop after popping back
                    self.context["return_to_cable_serial"] = cable_record['serial_number']
                    new_context = self.context.copy()
                    new_context["assign_cable_serial"] = cable_record['serial_number']
                    new_context["assign_cable_sku"] = cable_record['variant_sku']
                    return {'action': 'navigate', 'screen_result': ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, new_context)}

                elif choice_lower == 'u' and mode == 'lookup' and is_assigned:
                    self._unassign_cable(operator, cable_record)
                    continue

                elif choice_lower == 'p' and printer_available and cable_tested:
                    self.print_label_for_cable(operator, cable_record)
                    continue

                elif choice_lower == 'b' and printer_available:
                    self.print_barcode_for_cable(operator, cable_record)
                    continue

                elif choice_lower == 'l' and printer_available and has_reg_code:
                    self.print_registration_label(operator, cable_record)
                    continue

                elif choice_lower == 'd' and is_misc:
                    updated = self.edit_cable_description(operator, cable_record)
                    cable_record = updated
                    continue

                elif choice_lower == 'e' and mode == 'lookup' and not is_assigned:
                    new_context = self.context.copy()
                    new_context["selection_mode"] = "intake"
                    new_context["prefill_serial"] = cable_record['serial_number']
                    new_context["re_register"] = True
                    return {'action': 'navigate', 'screen_result': ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, new_context)}

                elif choice_lower == 'q':
                    return {'action': 'quit'}

                else:
                    # Check if input contains digits (likely a serial number)
                    if re.search(r'\d', choice):
                        return {'action': 'scan', 'serial': choice.strip().upper()}
                    # Otherwise ignore (accidental double-tap, etc.)
                    continue

            except KeyboardInterrupt:
                return {'action': 'quit'}


class ScanCableLookupScreen(CableScreenBase):
    """Main cable interface - scan to lookup, test, assign, or register cables"""

    def enter(self):
        """Publish scanning status while operator is active"""
        from greenlight.hardware.barcode_scanner import get_scanner
        scanner = get_scanner()
        if hasattr(scanner, 'set_scanning_active'):
            scanner.set_scanning_active(True)

    def exit(self):
        """Publish idle status when operator logs out"""
        from greenlight.hardware.barcode_scanner import get_scanner
        scanner = get_scanner()
        if hasattr(scanner, 'set_scanning_active'):
            scanner.set_scanning_active(False)

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        self._pending_serial = None

        # Check if we're returning from assignment and should show cable details
        return_to_cable = self.context.get("return_to_cable_serial")
        if return_to_cable:
            # Clear the return flag
            self.context.pop("return_to_cable_serial", None)
            # Load and show the cable details
            from greenlight.db import get_audio_cable
            cable_record = get_audio_cable(return_to_cable)
            if cable_record:
                result = self.cable_action_loop(operator, cable_record, mode='lookup')
                if result['action'] == 'navigate':
                    return result['screen_result']
                elif result['action'] == 'scan':
                    self._pending_serial = result['serial']
                # 'quit' falls through to continue scanning

        # Clear scanner queue at session start
        from greenlight.hardware.barcode_scanner import get_scanner
        scanner = get_scanner()
        if scanner.initialize():
            scanner.clear_queue()

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

        while True:
            # Check if we have a pending serial from cable_action_loop
            if self._pending_serial:
                serial_number = self._pending_serial
                self._pending_serial = None
            else:
                # Check if cable tester is available for calibrate option
                from greenlight.hardware.interfaces import hardware_manager
                cable_tester = hardware_manager.get_cable_tester()
                tester_available = cable_tester.connected if cable_tester else False

                # Update display
                self.ui.header(operator)
                self.ui.layout["body"].update(body_panel)
                row1 = "🔍 [bold green]Scan barcode[/bold green]"
                row2_parts = ["[cyan]'r'[/cyan] = Register cables"]
                if tester_available:
                    row2_parts.append("[cyan]'c'[/cyan] = Calibrate tester")
                row3_parts = [
                    "[cyan]'i'[/cyan] = Inventory",
                    "[cyan]'w'[/cyan] = Wholesale codes",
                    "[cyan]'p'[/cyan] = Wire labels",
                    "[cyan]'s'[/cyan] = Shopify scan mode",
                ]
                row4_parts = [
                    "[cyan]'f'[/cyan] = Fulfill order",
                    "[cyan]'l'[/cyan] = Lookup customer",
                    "[cyan]'q'[/cyan] = Logout",
                ]
                footer_text = "\n".join([
                    row1,
                    " | ".join(row2_parts),
                    " | ".join(row3_parts),
                    " | ".join(row4_parts),
                ])
                self.ui.layout["footer"].update(Panel(
                    footer_text,
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
            elif input_lower == 'i':
                # Go to inventory dashboard
                from greenlight.screens.inventory import InventoryDashboardScreen
                return ScreenResult(NavigationAction.PUSH, InventoryDashboardScreen, self.context.copy())
            elif input_lower == 'p':
                # Go to wire label printing
                from greenlight.screens.wire import WireLabelScreen
                return ScreenResult(NavigationAction.PUSH, WireLabelScreen, self.context.copy())
            elif input_lower == 's':
                # Enter Shopify scan mode (webhooks on, Greenlight paused)
                from greenlight.screens.shopify_scan import ShopifyScanModeScreen
                return ScreenResult(NavigationAction.PUSH, ShopifyScanModeScreen, self.context.copy())
            elif input_lower == 'f':
                # Fulfill order - go to customer lookup in fulfillment mode
                from greenlight.screens.orders import CustomerLookupScreen
                new_context = self.context.copy()
                new_context["fulfillment_mode"] = True
                return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, new_context)
            elif input_lower == 'l':
                # Standalone customer lookup (no fulfillment mode)
                from greenlight.screens.orders import CustomerLookupScreen
                return ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, self.context.copy())
            elif input_lower == 'c':
                # Run manual calibration
                self.run_manual_calibration(operator)
                continue

            # Validate input looks like a serial number (must be numeric)
            from greenlight.db import validate_serial_number
            valid, _ = validate_serial_number(serial_number)
            if not valid:
                continue

            # Otherwise treat as serial number lookup
            from greenlight.db import format_serial_number, get_audio_cable
            formatted_serial = format_serial_number(serial_number)
            cable_record = get_audio_cable(formatted_serial)

            # Clear console to refresh with new info
            self.ui.console.clear()

            if cable_record:
                # Show cable info and handle user actions
                result = self.cable_action_loop(operator, cable_record, mode='lookup')
                if result['action'] == 'navigate':
                    return result['screen_result']
                elif result['action'] == 'scan':
                    self._pending_serial = result['serial']
                    continue
                # 'quit' falls through to continue scanning
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

        # Display-friendly names for series
        series_display = {
            "Studio Classic": "Rayon Instrument (Studio Classic)",
            "Studio Vocal Classic": "Rayon XLR (Studio Vocal Classic)",
            "Tour Classic": "Cotton Instrument (Tour Classic)",
            "Tour Vocal Classic": "Cotton XLR (Tour Vocal Classic)",
        }

        # Create menu items — series only. Special Baby (MISC) and Limited
        # Edition (LTD) live one step deeper, alongside the standard patterns
        # for the chosen series.
        menu_items = [series_display.get(s, s) for s in series_options]
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
        if choice.lower() == "q" or choice == str(len(menu_items)):
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

        # Invalid choice - brief feedback, then re-display
        self.ui.console.print("[red]Invalid choice[/red]")
        import time; time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, SeriesSelectionScreen, self.context)


class LtdEditionPickerScreen(Screen):
    """Pick an active LTD edition to scan cables against.

    LTD edition CRUD lives in the Shopify app; this screen is read-only and
    just lets the operator pick which existing edition they're scanning for.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        from greenlight.db import list_ltd_editions
        from greenlight.cable_config import prefix_for_series

        # LTD editions are series-agnostic (Phase 5): the series picked
        # earlier in the flow only drives the per-cable prefix attached at
        # registration. Show every active edition here.
        series_prefix = prefix_for_series(selected_series) if selected_series else None
        editions = list_ltd_editions(active_only=True)

        self.ui.header(operator)

        if not editions:
            self.ui.layout["body"].update(Panel(
                "[bold yellow]No active Limited Editions[/bold yellow]\n\n"
                "Create an LTD edition in the Shopify app first, then come back\n"
                "to scan cables against it.",
                title="Limited Edition Picker", border_style="yellow"
            ))
            self.ui.layout["footer"].update(Panel(
                "Press enter or 'q' to go back",
                title=""
            ))
            self.ui.render()
            try:
                self.ui.console.input()
            except KeyboardInterrupt:
                pass
            return ScreenResult(NavigationAction.POP)

        # Build the picker list. Phase 4: an LTD edition is just a sku_group +
        # description. Length is per-cable now, captured on the next screen.
        body_lines = [
            "[bold yellow]Active Limited Editions[/bold yellow]\n"
        ]
        for i, ed in enumerate(editions, 1):
            description = ed.get('description') or ed.get('event_name') or '—'
            n_cables = ed.get('cable_count', 0)
            cable_word = '' if n_cables == 1 else 's'
            body_lines.append(
                f"  [green]{i}.[/green] [bold]{ed['slug']}[/bold] — {description}\n"
                f"     {n_cables} cable{cable_word} registered"
            )
        body_lines.append("")
        body_lines.append("  [green]Q[/green]. Back")

        self.ui.layout["body"].update(Panel(
            "\n".join(body_lines), title="Limited Edition Picker"
        ))
        self.ui.layout["footer"].update(Panel(
            "Pick an edition by number, or 'q' to go back",
            title="Choose"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice in ('q', ''):
            return ScreenResult(NavigationAction.POP)

        try:
            idx = int(choice) - 1
        except ValueError:
            self.ui.console.print("[red]Invalid choice[/red]")
            time.sleep(0.5)
            return ScreenResult(NavigationAction.REPLACE, LtdEditionPickerScreen, self.context)

        if 0 <= idx < len(editions):
            selected_sku = editions[idx]['sku']
            # Phase 5: LTD group SKU is series-agnostic ('LTD-PHISH26'), so
            # CableType needs the prefix passed in from screen context.
            try:
                cable_type = CableType()
                cable_type.load(selected_sku, prefix=series_prefix)
            except ValueError as e:
                self.ui.layout["body"].update(Panel(
                    f"❌ Error loading SKU {selected_sku}: {e}",
                    title="Error", style="red"
                ))
                self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
                self.ui.render()
                self.ui.console.input()
                return ScreenResult(NavigationAction.POP)

            new_context = self.context.copy()
            new_context["cable_type"] = cable_type
            # LTD/MISC variants need length + connector entered per-cable.
            return ScreenResult(NavigationAction.REPLACE, VariantLengthEntryScreen, new_context)

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, LtdEditionPickerScreen, self.context)


SPECIAL_BABY_OPTION = "Special Baby (MISC)"
LIMITED_EDITION_OPTION = "Limited Edition (LTD)"


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

        # Append specialty entries after the standard patterns. They route to
        # different downstream screens but live alongside the patterns from
        # the operator's perspective — the choice is "what kind of cable am
        # I scanning today?"
        menu_items = list(color_options)
        menu_items.append(SPECIAL_BABY_OPTION)
        menu_items.append(LIMITED_EDITION_OPTION)
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

        # Handle selection
        try:
            choice_idx = int(choice) - 1
            if not (0 <= choice_idx < len(menu_items) - 1):
                raise ValueError
            selected = menu_items[choice_idx]
            new_context = self.context.copy()

            if selected == SPECIAL_BABY_OPTION:
                return ScreenResult(NavigationAction.REPLACE, MiscVariantPickerScreen, new_context)
            if selected == LIMITED_EDITION_OPTION:
                return ScreenResult(NavigationAction.REPLACE, LtdEditionPickerScreen, new_context)

            # Standard pattern → length selection
            new_context["selected_color_pattern"] = selected
            return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice - brief feedback, then re-display
        self.ui.console.print("[red]Invalid choice[/red]")
        import time; time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, ColorPatternSelectionScreen, self.context)


SERIES_PREFIX_MAP = {
    'Studio Classic': 'SC',
    'Studio Patch': 'SP',
    'Studio Vocal Classic': 'SV',
    'Tour Classic': 'TC',
    'Tour Vocal Classic': 'TV',
}


def _format_length(length):
    """Render a length value as e.g. '10ft' or '10.5ft'."""
    try:
        val = float(length)
    except (TypeError, ValueError):
        return str(length) if length is not None else ""
    return f"{int(val)}ft" if val == int(val) else f"{val}ft"


class MiscVariantPickerScreen(Screen):
    """Pick an existing MISC variant for the selected series, or create a new one."""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        series_prefix = SERIES_PREFIX_MAP.get(selected_series)

        if not series_prefix:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"❌ Unknown series: {selected_series}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.POP)

        from greenlight.db import search_misc_variants
        existing = search_misc_variants(series_prefix)

        body_lines = [
            f"[bold yellow]Miscellaneous Cable — {selected_series}[/bold yellow]\n",
        ]
        if existing:
            body_lines.append("Existing MISC variants for this series:\n")
        else:
            body_lines.append("No existing MISC variants for this series yet.\n")

        menu_items = []
        for v in existing:
            n_cables = v.get('cable_count', 0)
            cable_word = '' if n_cables == 1 else 's'
            length = v.get('length')
            length_part = f"{_format_length(length)}, " if length is not None else ""
            label = f"{v['sku']}  ({length_part}{n_cables} cable{cable_word})  {v['description']}"
            menu_items.append(label)
        menu_items.append("[N] New MISC variant")
        menu_items.append("[Q] Back")

        rows = [
            f"[green]{i + 1}.[/green] {name}" if i < len(existing)
            else f"[green]{name}[/green]"
            for i, name in enumerate(menu_items)
        ]

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "\n".join(body_lines), title="Step 3: MISC Variant"
        ))
        self.ui.layout["footer"].update(Panel(
            "\n".join(rows),
            title="Pick a variant or press 'N' to create a new one"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("Choose: ").strip().lower()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if choice in ('q', ''):
            return ScreenResult(NavigationAction.POP)

        if choice == 'n':
            return ScreenResult(NavigationAction.REPLACE, MiscVariantCreateScreen, self.context)

        try:
            idx = int(choice) - 1
        except ValueError:
            self.ui.console.print("[red]Invalid choice[/red]")
            time.sleep(0.5)
            return ScreenResult(NavigationAction.REPLACE, MiscVariantPickerScreen, self.context)

        if 0 <= idx < len(existing):
            selected = existing[idx]
            try:
                cable_type = CableType()
                cable_type.load(selected['sku'])
            except ValueError as e:
                self.ui.layout["body"].update(Panel(
                    f"❌ Error loading SKU {selected['sku']}: {e}",
                    title="Error", style="red"
                ))
                self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
                self.ui.render()
                self.ui.console.input()
                return ScreenResult(NavigationAction.POP)

            # MISC groups are single-length; the picker shows that length and
            # the operator's selection commits to it. Skip the length entry
            # screen entirely.
            if selected.get('length') is None:
                # Empty group (no cables yet) — fall through to the length
                # prompt so the operator establishes the group's length.
                new_context = self.context.copy()
                new_context["cable_type"] = cable_type
                return ScreenResult(NavigationAction.REPLACE, VariantLengthEntryScreen, new_context)

            new_context = self.context.copy()
            new_context["cable_type"] = cable_type
            new_context["selected_length"] = selected['length']
            return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, MiscVariantPickerScreen, self.context)


class MiscVariantCreateScreen(Screen):
    """Create a new MISC variant: prompt for description, then length.

    Each MISC sku_group holds cables of a single length, so length is part
    of group identity (a same-description-different-length combo creates a
    new group). Operator commits to both up front.
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        selected_series = self.context.get("selected_series")
        series_prefix = SERIES_PREFIX_MAP.get(selected_series)

        if not series_prefix:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"❌ Unknown series: {selected_series}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.POP)

        # --- Step 1: description ---
        description = self._prompt_description(operator, selected_series)
        if description is None:
            return ScreenResult(NavigationAction.POP)

        # --- Step 2: length ---
        length_value = self._prompt_length(operator, selected_series, description)
        if length_value is None:
            return ScreenResult(NavigationAction.POP)

        # Resolve or create the MISC sku_group with both keys
        from greenlight.db import get_or_create_misc_sku
        new_sku = get_or_create_misc_sku(series_prefix, description, length_value)
        if not new_sku:
            self.ui.layout["body"].update(Panel(
                "❌ Failed to create MISC variant SKU. Check logs.",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.POP)

        try:
            cable_type = CableType()
            cable_type.load(new_sku)
        except ValueError as e:
            self.ui.layout["body"].update(Panel(
                f"❌ Error loading new SKU {new_sku}: {e}",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.POP)

        new_context = self.context.copy()
        new_context["cable_type"] = cable_type
        new_context["selected_length"] = length_value
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)

    def _prompt_description(self, operator, selected_series):
        max_desc_len = 90
        prefill_text = None
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]New MISC variant — {selected_series}[/bold yellow]\n\n"
            "[bold cyan]Step 1: enter a description for this variant:[/bold cyan]\n"
            "[dim](Length is the next step — don't include it here)[/dim]\n\n"
            "Include details like:\n"
            "  • Color/pattern (e.g., 'custom blue/orange')\n"
            "  • Connector types (e.g., 'Neutrik TS-TRS')\n"
            "  • Cable construction (e.g., 'cotton braid')\n"
            "  • Any special attributes\n\n"
            "Example: 'dark putty houndstooth with gold connectors instead of nickel'",
            title="MISC Variant — Description", border_style="yellow"
        ))

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

    def _prompt_length(self, operator, selected_series, description):
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]New MISC variant — {selected_series}[/bold yellow]\n"
            f"[dim]Description: {description}[/dim]\n\n"
            "[bold cyan]Step 2: enter cable length in feet[/bold cyan]\n"
            "Examples: 3, 6, 10, 15, 20, 25\n\n"
            "[dim]A MISC group is single-length: same description with a different length will\n"
            "create a separate sku_group.[/dim]",
            title="MISC Variant — Length", border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter length in feet (number only) or 'q' to go back",
            title="Length Entry"
        ))
        self.ui.render()

        try:
            length_input = self.ui.console.input("Length (ft): ").strip()
        except KeyboardInterrupt:
            return None

        if length_input.lower() == 'q' or not length_input:
            return None

        try:
            length_value = float(length_input)
            if length_value <= 0:
                raise ValueError("must be positive")
            return length_value
        except ValueError:
            self.ui.layout["body"].update(Panel(
                f"❌ Invalid length: {length_input}",
                title="Invalid Length", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
            self.ui.render()
            self.ui.console.input()
            return self._prompt_length(operator, selected_series, description)


class VariantLengthEntryScreen(Screen):
    """Free-form length entry for LTD cables (and the rare empty MISC group).

    LTD editions allow per-cable length so each scan goes through here.
    MISC groups are single-length — MiscVariantCreateScreen captures length
    upfront, and the picker auto-fills the existing group's length. The one
    case that still routes here for MISC is selecting an orphan empty group
    (no cables yet, length unknown) — the operator establishes the length
    on this screen.

    Catalog cables don't reach this screen — they use LengthSelectionScreen
    (YAML-driven list of standard lengths).
    """

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        if cable_type is None or not cable_type.is_loaded():
            return ScreenResult(NavigationAction.POP)

        scope = cable_type.name()
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[bold yellow]Enter cable length — {scope}[/bold yellow]\n\n"
            "[bold cyan]Length in feet[/bold cyan]\n"
            "Examples: 3, 6, 10, 15, 20, 25\n\n"
            "[dim]This length is stored on this specific cable only.[/dim]",
            title="Variant — Length", border_style="yellow"
        ))
        self.ui.layout["footer"].update(Panel(
            "Enter length in feet (number only) or 'q' to go back",
            title="Length Entry"
        ))
        self.ui.render()

        try:
            length_input = self.ui.console.input("Length (ft): ").strip()
        except KeyboardInterrupt:
            return ScreenResult(NavigationAction.POP)

        if length_input.lower() == 'q' or not length_input:
            return ScreenResult(NavigationAction.POP)

        try:
            length_value = float(length_input)
            if length_value <= 0:
                raise ValueError("must be positive")
        except ValueError:
            self.ui.layout["body"].update(Panel(
                f"❌ Invalid length: {length_input}",
                title="Invalid Length", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to try again", title=""))
            self.ui.render()
            self.ui.console.input()
            return ScreenResult(NavigationAction.REPLACE, VariantLengthEntryScreen, self.context)

        new_context = self.context.copy()
        new_context["selected_length"] = length_value
        # Reuse ConnectorTypeSelectionScreen for the connector pick — it
        # detects the variant flow via cable_type in context.
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)


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
                # Always go through connector selection — it handles the
                # auto-skip case for single-connector series internally.
                return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, new_context)
        except ValueError:
            pass

        # Invalid choice - brief feedback, then re-display
        self.ui.console.print("[red]Invalid choice[/red]")
        import time; time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, LengthSelectionScreen, self.context)


class ConnectorTypeSelectionScreen(Screen):
    """Pick a connector type. Handles both catalog and variant (MISC/LTD) flows.

    Catalog: came via series → pattern → length, no cable_type in context.
        Resolves (sku_group, length, connector_code) via resolve_catalog_variant
        at exit and routes to scan.

    Variant (MISC/LTD): came via picker → length entry, cable_type already in
        context. Just captures connector_code and routes to scan.
    """

    def run(self) -> ScreenResult:
        from greenlight.cable_config import (
            series_data_for_prefix, prefix_for_series, connector_display_for,
        )
        operator = self.context.get("operator", "")
        selected_length = self.context.get("selected_length")
        cable_type = self.context.get("cable_type")
        is_variant_flow = cable_type is not None and cable_type.is_loaded()

        # Determine the prefix to use for the connector list.
        if is_variant_flow:
            prefix = cable_type.prefix
            series_label = cable_type.series or prefix
            color_label = None
        else:
            selected_series = self.context.get("selected_series")
            selected_color = self.context.get("selected_color_pattern")
            prefix = prefix_for_series(selected_series)
            series_label = selected_series
            color_label = selected_color

        series_data = series_data_for_prefix(prefix) if prefix else None
        connectors = (series_data or {}).get('connectors') or []
        # Sort straight (code='') before right-angle (code='-R')
        connectors = sorted(connectors, key=lambda c: ((c.get('code') or '').startswith('-R'), c.get('display') or ''))

        if not connectors:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "No connector types found for the selected series",
                title="Error", style="red"
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        # Auto-skip if there's only one connector option (e.g. vocal series).
        if len(connectors) == 1:
            return self._finish(connectors[0], cable_type, is_variant_flow)

        menu_items = [c.get('display') or '?' for c in connectors]
        menu_items.append("Back (q)")
        rows = [f"[green]{i + 1}.[/green] {name}" for i, name in enumerate(menu_items)]

        body_lines = [f"Series: {series_label}"]
        if color_label:
            body_lines.append(f"Color: {color_label}")
        body_lines.append(f"Length: {selected_length} ft")
        body_lines.append("Select connector type")

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "\n".join(body_lines), title="Step 4: Connector Selection"
        ))
        self.ui.layout["footer"].update(Panel("\n".join(rows), title="Available Connectors"))
        self.ui.render()

        choice = self.ui.console.input("Choose: ")
        if choice.lower() == "q" or choice == str(len(menu_items)):
            return ScreenResult(NavigationAction.POP)

        try:
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(connectors):
                return self._finish(connectors[choice_idx], cable_type, is_variant_flow)
        except ValueError:
            pass

        self.ui.console.print("[red]Invalid choice[/red]")
        time.sleep(0.5)
        return ScreenResult(NavigationAction.REPLACE, ConnectorTypeSelectionScreen, self.context)

    def _finish(self, connector_dict, cable_type, is_variant_flow):
        """Capture the chosen connector and route to scan. Resolves the
        sku_group at exit for catalog flow."""
        connector_code = connector_dict.get('code') or ''
        connector_display = connector_dict.get('display') or ''
        new_context = self.context.copy()
        new_context['selected_connector'] = connector_display
        new_context['connector_code'] = connector_code

        if is_variant_flow:
            # MISC/LTD: cable_type already in context (the sku_group). Just
            # carry the connector_code through.
            return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)

        # Catalog: resolve to (sku_group, length, connector_code) and load
        # the CableType from sku_group.
        selected_series = self.context.get("selected_series")
        selected_color = self.context.get("selected_color_pattern")
        selected_length = self.context.get("selected_length")
        result = resolve_catalog_variant(
            selected_series, selected_color, selected_length, connector_display,
        )
        if not result:
            self.ui.layout["body"].update(Panel(
                "Could not resolve a SKU for the selected attributes",
                title="Error", style="red",
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("")
            return ScreenResult(NavigationAction.POP)

        # Phase 5: catalog group SKU is just a pattern code (e.g. 'GL') with
        # no prefix. resolve_catalog_variant returns prefix separately; thread
        # it into CableType so it can resolve series/connectors.
        try:
            new_cable_type = CableType()
            new_cable_type.load(result['sku_group'], prefix=result['prefix'])
        except ValueError as e:
            self.ui.layout["body"].update(Panel(
                f"Error loading sku_group: {e}", title="Error", style="red",
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("")
            return ScreenResult(NavigationAction.POP)

        new_context['cable_type'] = new_cable_type
        new_context['selected_length'] = result['length']
        new_context['connector_code'] = result['connector_code']
        return ScreenResult(NavigationAction.REPLACE, ScanCableIntakeScreen, new_context)


# ============================================================================
# Additional Cable Screens (from new_screens.py)
# ============================================================================


class ScanCableIntakeScreen(CableScreenBase):
    """Screen for scanning cables and registering them in the database"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        length = self.context.get("selected_length")
        connector_code = self.context.get("connector_code")

        if not cable_type or not cable_type.is_loaded():
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No cable type selected", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        if length is None or connector_code is None:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "Cable length and connector are required before scanning. "
                "Go back and complete the selection.",
                title="Missing variant attrs", style="red",
            ))
            self.ui.layout["footer"].update(Panel("Press enter to go back", title=""))
            self.ui.render()
            self.ui.console.input("Press enter to continue...")
            return ScreenResult(NavigationAction.POP)

        return self.scan_cables_loop(operator, cable_type, length, connector_code)

    def scan_cables_loop(self, operator, cable_type, length, connector_code):
        """Main scanning loop for registering multiple cables.

        Args:
            operator: Operator ID
            cable_type: CableType object (sku_group + display attrs)
            length: per-cable length in feet (numeric)
            connector_code: per-cable connector ('' or '-R')
        """
        scanned_count = 0
        scanned_serials = []
        # Use prefilled serial from "not found → register" flow if available
        self._pending_serial = self.context.get("prefill_serial")

        # Clear scanner queue at session start
        from greenlight.hardware.barcode_scanner import get_scanner
        scanner = get_scanner()
        if scanner.initialize():
            scanner.clear_queue()

        while True:
            # Check if we have a pending serial from cable_action_loop
            if self._pending_serial:
                serial_number = self._pending_serial
                self._pending_serial = None
            else:
                # Clear console before rendering to avoid layout corruption
                self.ui.console.clear()

                # Show current status
                self.ui.header(operator)

                from greenlight.cable_config import format_variant_sku
                length_for_format = int(length) if isinstance(length, float) and length.is_integer() else length
                variant_sku = format_variant_sku(
                    group_sku=cable_type.sku_group, prefix=cable_type.prefix,
                    length=length_for_format, connector_code=connector_code,
                ) or cable_type.sku_group
                scan_info = (
                    f"[bold cyan]Cable Type:[/bold cyan] {cable_type.name()}\n"
                    f"[bold cyan]SKU:[/bold cyan] {variant_sku}\n"
                    f"[bold cyan]Length:[/bold cyan] {_format_length(length)}"
                )
                if connector_code == '-R':
                    scan_info += "  [dim](right-angle)[/dim]"
                scan_info += "\n"
                if cable_type.kind in ('misc', 'ltd') and cable_type.description:
                    scan_info += f"[bold cyan]Description:[/bold cyan] {cable_type.description}\n"
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

            # Validate serial number is numeric
            from greenlight.db import validate_serial_number
            valid, error_msg = validate_serial_number(serial_number)
            if not valid:
                self.ui.console.print(f"[red]⚠️  {error_msg}[/red]")
                time.sleep(1.5)
                continue

            # Format the serial number (pad to 6 digits)
            formatted_serial = format_serial_number(serial_number)

            # Re-registering an existing cable lets the operator update test/operator fields,
            # but the SKU itself is locked once a cable has been registered (per design).
            allow_update = self.context.get("re_register", False)

            # Register the cable in database. Phase 5: register_scanned_cable
            # takes (serial, sku_group, prefix, length, connector_code, ...) —
            # prefix lives on audio_cables now since catalog/LTD group SKUs
            # dropped it.
            result = register_scanned_cable(
                serial_number, cable_type.sku_group, cable_type.prefix,
                length, connector_code,
                operator=operator, update_if_exists=allow_update,
            )

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

                # Re-register mode: just update the one cable and return to its info screen
                if self.context.get("re_register"):
                    self.context["return_to_cable_serial"] = saved_serial
                    break

                # Show cable info with action menu
                cable_record = get_audio_cable(saved_serial)
                if cable_record:
                    action_result = self.cable_action_loop(operator, cable_record, mode='intake')
                    if action_result['action'] == 'quit':
                        break
                    elif action_result['action'] == 'scan':
                        self._pending_serial = action_result['serial']
                    elif action_result['action'] == 'navigate':
                        return action_result['screen_result']
            else:
                # Error registering
                error_type = result.get('error', 'unknown')
                error_msg = result.get('message', 'Unknown error')

                if error_type == 'duplicate':
                    # Cable already exists
                    cable_record = get_audio_cable(formatted_serial)

                    if cable_record:
                        # Block re-registration if cable belongs to a customer
                        if cable_record.get('shopify_gid'):
                            self.ui.header(operator)
                            self.ui.layout["body"].update(self.build_cable_info_panel(cable_record))
                            self.ui.layout["footer"].update(Panel(
                                "[red]This cable is assigned to a customer and cannot be re-registered.[/red]\n"
                                "Press [bold green]enter[/bold green] or [cyan]'q'[/cyan] to continue scanning",
                                title="Assigned Cable"
                            ))
                            self.ui.render()
                            choice = self.get_serial_number_scan_or_manual()
                            if not choice or choice.strip().lower() == 'q':
                                break
                            # Treat any other input as a new serial scan
                            self._pending_serial = choice.strip().upper()
                            continue

                        # Show cable info with full action menu (test, print, etc.)
                        action_result = self.cable_action_loop(operator, cable_record, mode='intake')
                        if action_result['action'] == 'quit':
                            break
                        elif action_result['action'] == 'scan':
                            self._pending_serial = action_result['serial']
                        elif action_result['action'] == 'navigate':
                            return action_result['screen_result']
                        continue
                    else:
                        # Fallback to duplicate prompt if we can't get the record
                        existing = result.get('existing_record', {})
                        user_choice = self.show_duplicate_prompt(operator, cable_type, existing)

                        if user_choice == 'quit':
                            # User wants to quit scanning
                            break
                        elif user_choice == 'update':
                            update_result = register_scanned_cable(
                                serial_number, cable_type.sku_group, cable_type.prefix,
                                length, connector_code,
                                operator=operator, update_if_exists=True,
                            )
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

    def show_duplicate_prompt(self, operator, cable_type, existing_record):
        """Show duplicate record prompt and ask if user wants to update it

        Returns:
            'update' - User wants to update the record
            'skip' - User wants to skip this record
            'quit' - User wants to quit scanning
        """
        existing_serial = existing_record.get('serial_number', 'Unknown')
        existing_sku = existing_record.get('sku_group') or existing_record.get('sku', 'Unknown')
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
            f"  Group: {cable_type.sku_group}\n"
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
