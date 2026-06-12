"""
Wire Label Printing Screen

Looks up Sundial Wire products by SKU via Shopify and prints labels
with product name, SKU, and QR code linking to the product page.
"""

import logging
from rich.panel import Panel

from greenlight.screen_manager import Screen, ScreenResult, NavigationAction

logger = logging.getLogger(__name__)


class WireLabelScreen(Screen):
    """Screen for printing Sundial Wire product labels"""

    def run(self) -> ScreenResult:
        operator = self.context.get("operator", "")

        while True:
            # Show prompt for SKU entry
            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                "[bold cyan]Wire Label Printer[/bold cyan]\n\n"
                "Enter a Sundial Wire SKU to look up the product\n"
                "in Shopify and print a label.\n\n"
                "[dim]Scan barcode or type SKU manually[/dim]",
                title="Sundial Wire Labels"
            ))
            self.ui.layout["footer"].update(Panel(
                "Enter SKU or [cyan]'q'[/cyan] to go back",
                title="Wire Label", border_style="green"
            ))
            self.ui.render()

            try:
                sku_input = self.ui.console.input("SKU: ").strip()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.POP)

            if not sku_input or sku_input.lower() == 'q':
                return ScreenResult(NavigationAction.POP)

            # Normalize SKU to uppercase
            sku = sku_input.upper()

            # Look up SKU in Shopify
            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"Looking up SKU: [bold]{sku}[/bold]...",
                title="Searching Shopify"
            ))
            self.ui.layout["footer"].update(Panel("Please wait...", title=""))
            self.ui.render()

            from greenlight.shopify_client import get_product_by_sku, ShopifyConnectionError
            try:
                product = get_product_by_sku(sku)
            except ShopifyConnectionError as e:
                # Auth/connection failure — NOT a missing SKU. Surface it
                # distinctly so the operator checks credentials, not the SKU.
                self.ui.console.clear()
                self.ui.header(operator)
                self.ui.layout["body"].update(Panel(
                    "[bold red]Can't reach Shopify[/bold red]\n\n"
                    "The Sundial Wire store could not be reached or authenticated, "
                    f"so SKU [bold]{sku}[/bold] could not be looked up.\n\n"
                    "This is a connection/credentials issue, not a bad SKU.\n"
                    "Check the wire-store Shopify access token in .env.",
                    title="Shopify Unavailable", style="red"
                ))
                self.ui.layout["footer"].update(Panel(
                    "Press [cyan]Enter[/cyan] to try again",
                    title=""
                ))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    return ScreenResult(NavigationAction.POP)
                continue

            if not product:
                # SKU not found
                self.ui.console.clear()
                self.ui.header(operator)
                self.ui.layout["body"].update(Panel(
                    f"[bold red]SKU not found:[/bold red] {sku}\n\n"
                    "This SKU was not found in Shopify.\n"
                    "Check the SKU and try again.",
                    title="Not Found", style="red"
                ))
                self.ui.layout["footer"].update(Panel(
                    "Press [cyan]Enter[/cyan] to try another SKU",
                    title=""
                ))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    return ScreenResult(NavigationAction.POP)
                continue

            # Show product info and confirm
            product_title = product['product_title']
            variant_title = product['variant_title']
            product_sku = sku  # Use the entered SKU (base), not the variant SKU from Shopify
            handle = product['handle']
            price = product['price']
            product_url = f"https://sundialwire.com/products/{handle}" if handle else ""

            # Build display
            display_title = product_title
            if variant_title and variant_title != "Default Title":
                display_title = f"{product_title} - {variant_title}"

            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"[bold green]Product Found[/bold green]\n\n"
                f"[bold]Title:[/bold] {display_title}\n"
                f"[bold]SKU:[/bold] {product_sku}\n"
                f"[bold]Price:[/bold] ${price}\n"
                f"[bold]URL:[/bold] {product_url}\n\n"
                f"[dim]This info will be printed on the label[/dim]",
                title="Confirm Product", border_style="green"
            ))
            # Choose label type: customer-facing sample card (wire_label) vs
            # staff-facing bin label (bin_label, Code 128 SKU barcode for POS).
            self.ui.layout["footer"].update(Panel(
                "Label type: [cyan]'c'[/cyan] = sample card (default) | [cyan]'b'[/cyan] = bin label"
                " | [cyan]'s'[/cyan] = skip | [cyan]'q'[/cyan] = quit",
                title="Print Labels"
            ))
            self.ui.render()

            try:
                type_input = self.ui.console.input("Label type [c/b]: ").strip().lower()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.POP)

            if type_input == 'q':
                return ScreenResult(NavigationAction.POP)
            if type_input == 's':
                continue
            label_type = 'bin' if type_input == 'b' else 'card'

            self.ui.layout["footer"].update(Panel(
                "Enter [bold]quantity[/bold] (default 1) | [cyan]'s'[/cyan] = skip | [cyan]'q'[/cyan] = quit",
                title="Print Labels"
            ))
            self.ui.render()

            try:
                qty_input = self.ui.console.input("Qty: ").strip()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.POP)

            if qty_input.lower() == 'q':
                return ScreenResult(NavigationAction.POP)
            if qty_input.lower() == 's':
                continue

            # Parse quantity
            quantity = 1
            if qty_input:
                try:
                    quantity = int(qty_input)
                    if quantity < 1:
                        quantity = 1
                except ValueError:
                    quantity = 1

            # Print labels
            from greenlight.hardware.interfaces import hardware_manager, PrintJob

            label_printer = hardware_manager.get_label_printer()
            if not label_printer:
                self.ui.console.clear()
                self.ui.header(operator)
                self.ui.layout["body"].update(Panel(
                    "[bold red]No label printer available[/bold red]\n\n"
                    "Check printer connection and try again.",
                    title="Printer Error", style="red"
                ))
                self.ui.layout["footer"].update(Panel("Press Enter to continue", title=""))
                self.ui.render()
                try:
                    self.ui.console.input("")
                except KeyboardInterrupt:
                    pass
                continue

            # Use the product title (without variant) for the label
            label_title = product_title

            if label_type == 'bin':
                # Bin label: SKU barcode for Shopify POS pickup fulfillment.
                # No branding/QR; variant title (if any) becomes the subtitle.
                template = "bin_label"
                subtitle = variant_title if variant_title and variant_title != "Default Title" else ""
                label_data = {
                    'sku': product_sku,
                    'product_title': label_title,
                    'subtitle': subtitle,
                }
            else:
                # Sample card: customer-facing label with product-page QR.
                template = "wire_label"
                label_data = {
                    'product_title': label_title,
                    'sku': product_sku,
                    'product_url': product_url,
                }

            self.ui.console.clear()
            self.ui.header(operator)
            self.ui.layout["body"].update(Panel(
                f"Printing {quantity} label(s)...\n\n"
                f"{label_title}\n"
                f"{product_sku}",
                title="Printing", style="blue"
            ))
            self.ui.layout["footer"].update(Panel("Please wait...", title=""))
            self.ui.render()

            all_success = True
            for i in range(quantity):
                print_job = PrintJob(
                    template=template,
                    data=label_data,
                    quantity=1
                )
                success = label_printer.print_labels(print_job)
                if not success:
                    all_success = False
                    break

            # Show result
            self.ui.console.clear()
            self.ui.header(operator)
            if all_success:
                self.ui.layout["body"].update(Panel(
                    f"[bold green]Printed {quantity} label(s)[/bold green]\n\n"
                    f"{label_title}\n"
                    f"{product_sku}",
                    title="Print Complete", style="green"
                ))
            else:
                self.ui.layout["body"].update(Panel(
                    f"[bold red]Print failed[/bold red]\n\n"
                    f"Check printer and try again.",
                    title="Print Error", style="red"
                ))

            self.ui.layout["footer"].update(Panel(
                "Press [cyan]Enter[/cyan] to look up another SKU | [cyan]'q'[/cyan] to quit",
                title=""
            ))
            self.ui.render()

            try:
                next_input = self.ui.console.input("").strip().lower()
            except KeyboardInterrupt:
                return ScreenResult(NavigationAction.POP)

            if next_input == 'q':
                return ScreenResult(NavigationAction.POP)
            # Otherwise loop back for next SKU
