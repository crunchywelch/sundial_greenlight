"""
Shopify Scan Mode screen.

Temporarily re-enables Shopify webhooks and pauses Greenlight scan processing
so the shared barcode scanner can be used for Shopify order fulfillment.
"""

import logging
from rich.panel import Panel

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction

logger = logging.getLogger(__name__)


class ShopifyScanModeScreen(Screen):
    """Screen that routes scanner to Shopify while pausing Greenlight"""

    def enter(self):
        """Set scanner idle and pause Greenlight scan processing"""
        from greenlight.hardware.interfaces import hardware_manager
        scanner = hardware_manager.scanner
        if scanner and hasattr(scanner, 'set_scanning_active'):
            scanner.set_scanning_active(False)
            scanner.pause()
            logger.info("Shopify scan mode: status idle, Greenlight paused")

    def run(self) -> ScreenResult:
        operator = self.context.get("operator_name", "Operator")
        self.ui.header(operator)
        self.ui.layout["body"].update(Panel(
            "[bold cyan]Shopify Scan Mode Active[/bold cyan]\n\n"
            "Scanner is now routing to Shopify for order fulfillment.\n"
            "Greenlight scan processing is paused.\n\n"
            "[dim]Scan barcodes for Shopify orders, then press any key to return.[/dim]",
            title="Shopify Scan Mode",
            border_style="cyan"
        ))
        self.ui.layout["footer"].update(Panel(
            "[cyan]Press any key[/cyan] to exit Shopify mode and resume Greenlight",
            title="Options", border_style="cyan"
        ))
        self.ui.render()

        # Wait for any keypress
        self.ui.console.input("")

        return ScreenResult(NavigationAction.POP)

    def exit(self):
        """Set scanner active and resume Greenlight scan processing"""
        from greenlight.hardware.interfaces import hardware_manager
        scanner = hardware_manager.scanner
        if scanner and hasattr(scanner, 'set_scanning_active'):
            scanner.set_scanning_active(True)
            scanner.resume()
            logger.info("Shopify scan mode ended: status scanning, Greenlight resumed")
