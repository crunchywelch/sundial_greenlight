"""Test wire label printing through the same code path as the app."""

import sys
import logging
from greenlight.hardware.tsc_label_printer import TSCLabelPrinter
from greenlight.hardware.interfaces import PrintJob

logging.basicConfig(level=logging.INFO)

PRINTER_IP = "192.168.0.52"

# Default test data, or pass a real SKU as argument to look it up
if len(sys.argv) > 1:
    sku = sys.argv[1].upper()
    print(f"Looking up SKU: {sku}")
    from greenlight.shopify_client import get_product_by_sku
    product = get_product_by_sku(sku)
    if not product:
        print(f"SKU {sku} not found in Shopify")
        sys.exit(1)

    label_data = {
        'product_title': product['product_title'],
        'sku': sku,  # Use the entered SKU (base), not the variant SKU from Shopify
        'product_url': f"https://sundialwire.com/products/{product['handle']}",
    }
    print(f"Found: {product['product_title']}")
    print(f"  Label SKU: {sku}")
    print(f"  Shopify:   {product['sku']} ({product['variant_title']})")
    print(f"  Handle:    {product['handle']}")
    print(f"  Price:     ${product['price']}")
else:
    label_data = {
        'product_title': 'TEST LABEL - Instrument Cable Black',
        'sku': 'TEST-SKU-000',
        'product_url': 'https://sundialwire.com/products/test',
    }
    print("Using test data (pass a SKU as argument to look up from Shopify)")

print(f"\nLabel data:")
for k, v in label_data.items():
    print(f"  {k}: {v}")

printer = TSCLabelPrinter(PRINTER_IP)
if not printer.initialize():
    print(f"\nCouldn't connect to printer at {PRINTER_IP}")
    sys.exit(1)

print(f"\nPrinter connected at {PRINTER_IP}")

print_job = PrintJob(
    template="wire_label",
    data=label_data,
    quantity=1,
)

success = printer.print_labels(print_job)
print(f"Result: {'OK' if success else 'FAILED'}")
