"""Scan hub: scan a serial to look up/test a cable, or jump to other areas."""

import logging
import time

from rich.panel import Panel

from greenlight.screen_manager import ScreenResult, NavigationAction
from greenlight.screens.cable.base import CableScreenBase
from greenlight.screens.cable.intake_select import SeriesSelectionScreen

logger = logging.getLogger(__name__)


class ScanCableLookupScreen(CableScreenBase):
    """Main cable interface - scan to look up, test, assign, or take in cables"""

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
                row2_parts = ["[cyan]'r'[/cyan] = Intake cables"]
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
                # Go to intake flow
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
                # Fulfill order. Lands on every unfulfilled order rather than
                # a customer lookup: an operator with a bench of tested
                # cables is asking what's outstanding, not who it's for.
                # Customer lookup is still one key away from there.
                from greenlight.screens.orders import FulfillOrdersScreen
                new_context = self.context.copy()
                new_context["fulfillment_mode"] = True
                return ScreenResult(NavigationAction.PUSH, FulfillOrdersScreen, new_context)
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
            valid, error_msg = validate_serial_number(serial_number)
            if not valid:
                # Stay quiet for stray keystrokes, but explain a scanned UPC
                from greenlight.gtin import looks_like_gtin12
                if looks_like_gtin12(serial_number):
                    self.ui.console.print(f"[red]⚠️  {error_msg}[/red]")
                    time.sleep(1.5)
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
                # Cable not found - offer intake
                intake_result = self.show_not_found_with_intake(operator, formatted_serial)
                if intake_result:
                    return intake_result
                # If no result, continue scanning
                body_panel = Panel(
                    "🔍 Ready to Scan\n\n"
                    "[dim]Waiting for scan...[/dim]",
                    title="Greenlight Cable Station"
                )

    def show_not_found_with_intake(self, operator, serial_number):
        """Show not found message with option to take the cable in

        Returns:
            ScreenResult if user chooses intake, None to continue scanning
        """
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            f"❌ [bold red]Cable Not Found[/bold red]\n\n"
            f"Serial Number: [yellow]{serial_number}[/yellow]\n\n"
            f"This cable is not in the database.\n"
            f"Would you like to take it in?",
            title="Not in Database", style="red"
        ))
        self.ui.layout["footer"].update(Panel(
            "[cyan]'r'[/cyan] = Intake this cable | [cyan]Enter[/cyan] = Continue scanning",
            title="Options"
        ))
        self.ui.render()

        try:
            choice = self.ui.console.input("").strip().lower()

            if choice == 'r':
                # Go to intake flow with this serial number pre-filled
                new_context = self.context.copy()
                new_context["selection_mode"] = "intake"
                new_context["prefill_serial"] = serial_number
                return ScreenResult(NavigationAction.PUSH, SeriesSelectionScreen, new_context)

            # Otherwise continue scanning
            return None

        except KeyboardInterrupt:
            return None
