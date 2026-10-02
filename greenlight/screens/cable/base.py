"""Shared cable screen behaviour: lookup display, QC testing, assignment."""

import logging
import readline
import re
import time

from rich.panel import Panel
from rich.table import Table

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction
from greenlight.db import get_audio_cable, update_cable_test_results

logger = logging.getLogger(__name__)


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
[bold yellow]Updated:[/bold yellow] {updated_timestamp_str}

[bold cyan]Cable Details:[/bold cyan]
  Series: {series}
  Length: {length} ft"""

        # pattern_name is catalog-only (None for MISC/LTD); connector_display
        # is set for any known prefix.
        if pattern_name:
            left += f"\n  Color: {pattern_name}"
        if connector_display:
            left += f"\n  Connector: {connector_display}"
        connector_finish_display = cable_record.get("connector_finish_display")
        if connector_finish_display:
            left += f"\n  Finish: {connector_finish_display}"

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
        elif cable_record.get("wholesale_company_gid"):
            # Sold to a dealer but not yet claimed: shopify_gid is deliberately
            # NULL so the end buyer can register. "Not assigned" would read as
            # though nothing had happened to the cable.
            right += """

[bold magenta]Owner:[/bold magenta]
  [yellow]⏳ Awaiting end-buyer registration[/yellow]"""
        else:
            right += """

[bold magenta]Assignment:[/bold magenta]
  [yellow]⏳ Not assigned[/yellow]"""

        # Wholesale dealer. Independent of the customer block above: a cable sold
        # to a dealer has no shopify_gid until its end buyer registers it, so both
        # sections can show at once once that happens.
        wholesale_company_gid = cable_record.get("wholesale_company_gid")
        if wholesale_company_gid:
            from greenlight import shopify_client
            # Cached in shopify_client, so this doesn't hit the API on every render.
            dealer = shopify_client.get_company_display(
                wholesale_company_gid, cable_record.get("wholesale_location_gid")
            ) or f"[yellow]{wholesale_company_gid}[/yellow]"
            right += f"\n\n[bold yellow]🏪 Sold via:[/bold yellow]\n  {dealer}"
            registered_at = cable_record.get("registered_at")
            if registered_at:
                right += f"\n  [dim]Registered {registered_at.strftime('%Y-%m-%d')}[/dim]"
            else:
                right += "\n  [dim]Not yet registered by end buyer[/dim]"

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

        # Whether to run the XLR shell-bond test. The standard catalog pairs
        # cotton/Tour with conductive nickel shells and rayon/Studio with coated
        # black shells, so for catalog cables the series tells us (is_touring).
        # Custom/LTD builds can use any connector, so an explicit per-cable
        # connector_finish overrides that assumption: black/gold Neutrik shells
        # are non-conductive (skip) while nickel shells bond (test).
        from greenlight.cable_config import finish_tests_shell
        connector_finish = cable_record.get('connector_finish')
        if connector_finish:
            should_test_shell = finish_tests_shell(connector_finish)
        else:
            should_test_shell = is_touring

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

        # Run shell bond test (only when the connectors have a conductive shell,
        # and skip if continuity already failed)
        if should_test_shell and all_passed:
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
        elif should_test_shell:
            shell_status = "[dim]SKIP[/dim]"

        # Only run resistance test if continuity passed
        if all_passed:
            if should_test_shell:
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
        if should_test_shell:
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
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()

        try:
            self.ui.wait_back()
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
            return False

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
            'connector_finish': cable_record.get('connector_finish_display'),
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
        return label_printer.print_labels(print_job)

    def print_registration_label(self, operator, cable_record):
        """Generate a registration code if needed and print a registration label.

        Mirrors the wholesale batch screen for a single cable: if the cable has
        no registration code yet, one is generated and saved to the database,
        then the registration label (code + QR) is printed. If the cable already
        has a code, the existing label is reprinted.

        Args:
            operator: Operator ID
            cable_record: Cable record from database

        Returns:
            The (possibly updated) cable record.
        """
        from greenlight.hardware.interfaces import hardware_manager, PrintJob
        from greenlight.registration import generate_registration_url
        from greenlight.db import batch_assign_registration_codes

        label_printer = hardware_manager.get_label_printer()
        if not label_printer:
            return cable_record

        serial_number = cable_record.get('serial_number', '')

        reg_code = cable_record.get('registration_code', '')
        if not reg_code:
            # Generate + save a code (with collision retry) just like wholesale.
            result = batch_assign_registration_codes([serial_number])
            results_list = result.get('results', [])
            if results_list:
                reg_code = results_list[0]['registration_code']
                cable_record['registration_code'] = reg_code
                # No inventory sync: a code doesn't remove a cable from stock.
                # See get_available_count_for_sku.
            else:
                errors = result.get('errors', [])
                message = errors[0]['error'] if errors else result.get('message', 'Failed to generate registration code')
                self._flash_message(operator, cable_record, f"[bold red]{message}[/bold red]")
                return cable_record

        reg_url = generate_registration_url(reg_code)

        print_job = PrintJob(
            template="registration_label",
            data={
                'registration_code': reg_code,
                'registration_url': reg_url,
                'serial_number': serial_number,
                'sku': cable_record.get('sku', ''),
            },
            quantity=1,
        )
        label_printer.print_labels(print_job)
        return cable_record

    def _flash_message(self, operator, cable_record, message):
        """Briefly show a message in the footer over the cable info panel."""
        self.ui.console.clear()
        self.ui.header(operator)
        self.ui.layout["body"].update(self.build_cable_info_panel(cable_record))
        self.ui.layout["footer"].update(Panel(f"{message}\nPress Enter to continue", title=""))
        self.ui.render()
        try:
            self.ui.console.input("")
        except KeyboardInterrupt:
            pass

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
        """Prompt for confirmation and release a cable from a commercial channel.

        A cable can be committed to both at once — sold to a dealer, then
        registered by the buyer who bought it from that dealer. In that case the
        operator picks which to release, because clearing both would destroy the
        dealer attribution.
        """
        from greenlight import shopify_client, db as db_mod

        serial = cable_record['serial_number']
        customer_gid = cable_record.get('shopify_gid', '')
        company_gid = cable_record.get('wholesale_company_gid', '')

        customer_name = None
        if customer_gid:
            customer_name = "unknown customer"
            try:
                customer = shopify_client.get_customer_by_id(customer_gid.split('/')[-1])
                if customer:
                    customer_name = customer.get('displayName') or customer_name
            except Exception:
                pass

        dealer_name = None
        if company_gid:
            dealer_name = shopify_client.get_company_display(
                company_gid, cable_record.get('wholesale_location_gid')
            ) or company_gid

        both = bool(customer_gid and company_gid)

        self.ui.header(operator)
        if both:
            body = (
                f"[yellow]Cable {serial} is committed to two parties.[/yellow]\n\n"
                f"  [cyan]c[/cyan]  Owner:  {customer_name}\n"
                f"  [cyan]d[/cyan]  Dealer: {dealer_name}\n\n"
                f"Releasing one leaves the other intact. Clearing the dealer would\n"
                f"lose the record of which store sold this cable."
            )
            footer = "[cyan]c[/cyan] = Release owner | [cyan]d[/cyan] = Release dealer | [cyan]n[/cyan] = Cancel"
        else:
            holder = f"[cyan]{customer_name}[/cyan]" if customer_gid else f"dealer [cyan]{dealer_name}[/cyan]"
            note = ""
            if company_gid:
                note = ("\n[yellow]The cable keeps its registration code, so it stays out of "
                        "retail inventory. Clear the code separately to return it to "
                        "shopify.com.[/yellow]")
            elif cable_record.get('shopify_order_gid'):
                note = "\n[yellow]This cable is also assigned to an order — both will be cleared.[/yellow]"
            body = (
                f"[yellow]Unassign cable {serial}?[/yellow]\n\n"
                f"Currently assigned to: {holder}{note}\n\n"
                f"This will return the cable to available inventory."
            )
            footer = "[green]y[/green] = Confirm unassign | [cyan]n[/cyan] = Cancel"

        self.ui.layout["body"].update(Panel(body, title="Unassign Cable"))
        self.ui.layout["footer"].update(Panel(footer, title="Confirm?"))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return

        if both:
            channel = {'c': 'retail', 'd': 'wholesale'}.get(choice)
            if not channel:
                return
        else:
            if choice not in ('y', 'yes'):
                return
            channel = 'retail' if customer_gid else 'wholesale'

        result = db_mod.unassign_cable(serial, channel=channel)
        if result.get('success'):
            # Availability may have gone up — push the new count to Shopify.
            from greenlight.shopify_client import sync_inventory_for_cable
            ok, err = sync_inventory_for_cable(cable_record)
            if not ok:
                logger.warning(f"Shopify inventory sync failed for {serial}: {err}")
            released = "owner" if channel == 'retail' else "dealer"
            self.ui.layout["body"].update(Panel(
                f"[bold green]Cable {serial}: {released} released.[/bold green]",
                title="Unassigned", style="green"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"[red]Error: {result.get('message', 'Unknown error')}[/red]",
                title="Error"
            ))
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()
        self.ui.wait_back()

    def _clear_registration_code(self, operator, cable_record):
        """Prompt for confirmation and clear a cable's registration code.

        Clearing a code does not change availability — a coded cable is still
        ours and still sellable (see db.get_available_count_for_sku). This just
        detaches the code, e.g. after a mis-scan or a reprint under a new code.
        """
        from greenlight import db as db_mod

        serial = cable_record['serial_number']
        reg_code = cable_record.get('registration_code', '')

        # A cable sold to a dealer shipped with a printed label carrying this
        # code. Clearing it would leave the end buyer unable to register the
        # cable they bought, with nothing on our side explaining why.
        if cable_record.get('wholesale_company_gid'):
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"[red]Cable {serial} has been sold to a dealer — its registration "
                f"code can't be cleared.[/red]\n\n"
                f"It shipped with a label carrying this code; clearing it would "
                f"leave the buyer unable to register the cable.\n\n"
                f"If this was a mistake, unassign the cable from its wholesale "
                f"order first, then clear the code.",
                title="Sold to Dealer", style="red"
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return

        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"[yellow]Clear registration code for {serial}?[/yellow]\n\n"
            f"Current code: [cyan]{reg_code}[/cyan]\n\n"
            f"[yellow]Any registration label already printed for this code "
            f"will no longer work — destroy it.[/yellow]",
            title="Clear Registration Code"
        ))
        self.ui.layout["footer"].update(Panel(
            "[green]y[/green] = Confirm clear | [cyan]n[/cyan] = Cancel",
            title="Confirm?"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()
        except KeyboardInterrupt:
            return

        if choice not in ('y', 'yes'):
            return

        result = db_mod.clear_registration_code(serial)
        if result.get('success'):
            cable_record['registration_code'] = None
            self.ui.layout["body"].update(Panel(
                f"[bold green]Registration code {reg_code} cleared.[/bold green]",
                title="Code Cleared", style="green"
            ))
        else:
            self.ui.layout["body"].update(Panel(
                f"[red]Error: {result.get('message', 'Unknown error')}[/red]",
                title="Error"
            ))
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()
        self.ui.wait_back()

    def show_cable_history(self, operator, cable_record):
        """Show the cable_events audit trail for this cable."""
        from greenlight.db import get_cable_events

        serial = cable_record['serial_number']
        events = get_cable_events(serial, limit=self.ui.page_size(reserved=22))

        self.ui.console.clear()
        self.ui.header(operator)

        if events:
            table = Table(show_header=True, header_style="bold magenta", expand=True)
            table.add_column("When", style="dim", width=17)
            table.add_column("Event", style="cyan", width=20)
            table.add_column("By", width=8)
            table.add_column("Detail", overflow="fold")

            for e in events:
                detail = e.get('detail') or {}
                parts = []
                for key in ('from', 'to'):
                    if key in detail and detail[key] is not None:
                        val = detail[key]
                        if isinstance(val, dict):
                            val = ' '.join(f"{k}={v}" for k, v in val.items() if v is not None)
                        elif isinstance(val, str) and val.startswith('gid://'):
                            # GIDs are unreadable in a table; the tail identifies it
                            val = f"…/{val.rsplit('/', 1)[-1]}"
                        parts.append(f"{key}: {val}")
                for key, val in detail.items():
                    if key not in ('from', 'to') and val is not None:
                        parts.append(f"{key}={val}")
                table.add_row(
                    e['created_at'].strftime('%Y-%m-%d %H:%M'),
                    e['event'],
                    e.get('actor') or '—',
                    '  '.join(parts),
                )
            body = table
        else:
            body = ("[dim]No recorded history for this cable.[/dim]\n\n"
                    "[dim]Events are recorded from the point the audit trail was added; "
                    "earlier changes were not captured.[/dim]")

        self.ui.layout["body"].update(Panel(
            body, title=f"📜 History — {serial}", style="cyan"
        ))
        self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
        self.ui.render()
        self.ui.wait_back()

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
            has_reg_code = bool(cable_record.get('registration_code'))
            sold_to_dealer = bool(cable_record.get('wholesale_company_gid'))
            # Committed either way: registered to an end owner, or sold to a
            # dealer. Its SKU is now on someone's invoice and must not change.
            is_committed = is_assigned or sold_to_dealer

            # Build footer options based on mode and hardware
            footer_options = []
            if tester_available:
                footer_options.append("[cyan]'t'[/cyan] = Test cable")
            if mode == 'lookup' and not is_committed:
                footer_options.append("[cyan]'a'[/cyan] = Assign cable")
            if mode == 'lookup' and is_committed:
                footer_options.append("[cyan]'u'[/cyan] = Unassign cable")
            if printer_available and cable_tested:
                footer_options.append("[cyan]'p'[/cyan] = Print label")
            if printer_available:
                footer_options.append("[cyan]'l'[/cyan] = Print reg label")
            if mode == 'lookup' and has_reg_code:
                footer_options.append("[cyan]'c'[/cyan] = Clear reg code")
            if is_misc:
                footer_options.append("[cyan]'d'[/cyan] = Edit description")
            if mode == 'lookup' and not is_committed:
                footer_options.append("[cyan]'e'[/cyan] = Change SKU")
            footer_options.append("[cyan]'h'[/cyan] = History")
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

                elif choice_lower == 'a' and mode == 'lookup' and not is_committed:
                    from greenlight.screens.orders import CustomerLookupScreen
                    # Set return flag on our own context so ScanCableLookupScreen
                    # re-enters cable_action_loop after popping back
                    self.context["return_to_cable_serial"] = cable_record['serial_number']
                    new_context = self.context.copy()
                    new_context["assign_cable_serial"] = cable_record['serial_number']
                    new_context["assign_cable_sku"] = cable_record['variant_sku']
                    return {'action': 'navigate', 'screen_result': ScreenResult(NavigationAction.PUSH, CustomerLookupScreen, new_context)}

                elif choice_lower == 'u' and mode == 'lookup' and is_committed:
                    self._unassign_cable(operator, cable_record)
                    continue

                elif choice_lower == 'p' and printer_available and cable_tested:
                    self.print_label_for_cable(operator, cable_record)
                    continue

                elif choice_lower == 'l' and printer_available:
                    cable_record = self.print_registration_label(operator, cable_record)
                    continue

                elif choice_lower == 'c' and mode == 'lookup' and has_reg_code:
                    self._clear_registration_code(operator, cable_record)
                    continue

                elif choice_lower == 'd' and is_misc:
                    updated = self.edit_cable_description(operator, cable_record)
                    cable_record = updated
                    continue

                elif choice_lower == 'e' and mode == 'lookup' and not is_committed:
                    # Return to this cable's info screen when the edit flow pops back
                    self.context["return_to_cable_serial"] = cable_record['serial_number']
                    new_context = self.context.copy()
                    new_context.pop("return_to_cable_serial", None)
                    new_context["selection_mode"] = "intake"
                    new_context["prefill_serial"] = cable_record['serial_number']
                    new_context['sku_change'] = True
                    from greenlight.screens.cable.intake_select import SeriesSelectionScreen
                    return {'action': 'navigate', 'screen_result': ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, new_context)}

                elif choice_lower == 'h':
                    self.show_cable_history(operator, cable_record)
                    continue

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
