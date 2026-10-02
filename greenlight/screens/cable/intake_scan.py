"""Intake scanning: record pre-labelled serials against the selected SKU."""

import logging
import time

from rich.panel import Panel

from greenlight.screen_manager import ScreenResult, NavigationAction
from greenlight.db import get_audio_cable, intake_scanned_cable, format_serial_number
from greenlight.screens.cable.base import CableScreenBase
from greenlight.screens.cable.intake_select import _format_length
from greenlight.screens.cable.lookup import ScanCableLookupScreen

logger = logging.getLogger(__name__)


class ScanCableIntakeScreen(CableScreenBase):
    """Screen for scanning cables and registering them in the database"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")
        cable_type = self.context.get("cable_type")
        length = self.context.get("selected_length")
        connector_code = self.context.get("connector_code")
        connector_finish = self.context.get("connector_finish")

        if not cable_type or not cable_type.is_loaded():
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel("No cable type selected", title="Error", style="red"))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        if length is None or connector_code is None:
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "Cable length and connector are required before scanning. "
                "Go back and complete the selection.",
                title="Missing variant attrs", style="red",
            ))
            self.ui.layout["footer"].update(Panel("[green]q.[/green] Back", title=""))
            self.ui.render()
            self.ui.wait_back()
            return ScreenResult(NavigationAction.POP)

        return self.scan_cables_loop(operator, cable_type, length, connector_code,
                                     connector_finish)

    def scan_cables_loop(self, operator, cable_type, length, connector_code,
                         connector_finish=None):
        """Main scanning loop for registering multiple cables.

        Args:
            operator: Operator ID
            cable_type: CableType object (sku_group + display attrs)
            length: per-cable length in feet (numeric)
            connector_code: per-cable connector ('' or '-R')
            connector_finish: per-cable connector finish for custom/LTD XLR
                builds (e.g. 'nickel', 'black_gold'); None for catalog.
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
                if connector_finish:
                    from greenlight.cable_config import finish_display
                    fin = finish_display(connector_finish)
                    if fin:
                        scan_info += f"\n[bold cyan]Finish:[/bold cyan] {fin}"
                scan_info += "\n"
                if cable_type.kind in ('misc', 'ltd') and cable_type.description:
                    scan_info += f"[bold cyan]Description:[/bold cyan] {cable_type.description}\n"
                scan_info += f"\n[bold yellow]Scanned:[/bold yellow] {scanned_count} cable{'s' if scanned_count != 1 else ''}"
                if scanned_serials:
                    recent = scanned_serials[-5:]
                    scan_info += f"\n[dim]Recent: {', '.join(recent)}[/dim]"

                self.ui.layout["body"].update(Panel(
                    scan_info,
                    title="📦 Cable Intake",
                    subtitle="Scan barcode labels to take cables into inventory"
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

            # Re-running intake on an existing cable lets the operator correct its
            # SKU/length/connector. Distinct from the buyer registration flow —
            # see the sku_changed cable event.
            allow_update = self.context.get('sku_change', False)

            # Take the cable into inventory. Phase 5: intake_scanned_cable
            # takes (serial, sku_group, prefix, length, connector_code, ...) —
            # prefix lives on audio_cables now since catalog/LTD group SKUs
            # dropped it.
            result = intake_scanned_cable(
                serial_number, cable_type.sku_group, cable_type.prefix,
                length, connector_code,
                operator=operator, update_if_exists=allow_update,
                connector_finish=connector_finish,
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

                # SKU-change mode: update the one cable and return to its info
                # screen (the lookup screen set return_to_cable_serial on 'e')
                if self.context.get('sku_change'):
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
                            update_result = intake_scanned_cable(
                                serial_number, cable_type.sku_group, cable_type.prefix,
                                length, connector_code,
                                operator=operator, update_if_exists=True,
                                connector_finish=connector_finish,
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

        # Pop back to the lookup screen underneath. Don't REPLACE with our own
        # context — it carries this intake's cable_type/selections, which
        # would leak into the next intake flow.
        return ScreenResult(NavigationAction.POP, pop_to=ScanCableLookupScreen)

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
