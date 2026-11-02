#!/usr/bin/env python3
"""
Print the retail labels for a wholesale order, each on the printer holding its stock.

Wholesale orders arrive as Shopify DRAFT orders: the B2B flow in
shopify_app/app/b2b.server.js creates a draft and emails an invoice, and
never completes it -- the buyer paying is what turns it into an Order. So an
unpaid wholesale order is a draft, which is the state its labels get printed
in, and `get_customer_orders()` cannot see it.

Which labels to print is asked per job rather than fixed, because it varies:
not every retailer takes the UPC label, and the Prop 65 warning is only wanted
on retail-boxed goods.

Registration labels are NOT printed here. Those carry a unique code per
physical cable, keyed to serial numbers that live in Postgres rather than in
the order, so Greenlight's order scan screen prints each one as its cable is
scanned (`f`), and `w` prints them for cables not on an order.

Usage:
    python tools/printer/print_order_labels.py --list
    python tools/printer/print_order_labels.py D14 --preview
    python tools/printer/print_order_labels.py D14 --labels side,prop65
    python tools/printer/print_order_labels.py D14

Options:
    --list        Show recent draft orders and exit
    --labels      Comma-separated: upc, side, prop65  (default: all three)
    --preview     Show the plan and exit, printing nothing
    --mock        Use the mock printer (no hardware)
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from greenlight.hardware.interfaces import PrintJob
from greenlight.hardware.tsc_label_printer import build_label_printers
from greenlight.label_batch import describe_plan, plan_order

# What --labels accepts, and the template each name maps to.
LABEL_CHOICES = {"upc": "box_label", "side": "shelf_label",
                 "prop65": "prop65_label"}


def list_drafts(limit):
    from greenlight.shopify_client import get_draft_orders
    rows = get_draft_orders(limit=limit)
    if not rows:
        print("\n  No draft orders found.\n")
        return 1
    print(f"\n  {len(rows)} recent draft order(s):\n")
    from greenlight.screens.order_labels import draft_lifecycle
    for d in rows:
        customer = (d.get("customer") or {}).get("displayName") or "?"
        cables = sum(li["quantity"] for li in d["line_items"])
        print(f"    {d['name']:7} {customer:22} "
              f"{len(d['line_items'])} line(s), {cables:3} cable(s)   "
              f"{draft_lifecycle(d)}")
    print()
    return 0


def resolve_upcs(plan_templates):
    """SKU -> UPC from Shopify, only if some template actually needs one.

    One bulk call rather than one per SKU; Shopify's variant `barcode` field
    is the source of truth for retail UPCs.
    """
    if "box_label" not in plan_templates:
        return {}
    from greenlight.shopify_client import get_all_product_skus
    return {sku: v.get("barcode")
            for sku, v in get_all_product_skus().items() if v.get("barcode")}


def main():
    parser = argparse.ArgumentParser(
        description="Print retail labels for a wholesale draft order.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("order", nargs="?",
                        help='Draft order name, e.g. D14 or "#D14"')
    parser.add_argument("--list", action="store_true", dest="list_only",
                        help="Show recent draft orders and exit")
    parser.add_argument("--limit", type=int, default=25,
                        help="How many drafts --list shows (default 25)")
    parser.add_argument("--labels", default=",".join(LABEL_CHOICES),
                        help=f"Comma-separated: {', '.join(LABEL_CHOICES)} "
                             f"(default: all)")
    parser.add_argument("--preview", action="store_true",
                        help="Show the plan and exit, printing nothing")
    parser.add_argument("--mock", action="store_true",
                        help="Use the mock printer (no hardware)")
    args = parser.parse_args()

    if args.list_only:
        return list_drafts(args.limit)
    if not args.order:
        parser.print_help()
        return 1

    wanted = [w.strip().lower() for w in args.labels.split(",") if w.strip()]
    bad = [w for w in wanted if w not in LABEL_CHOICES]
    if bad:
        sys.exit(f"Error: unknown label type(s) {', '.join(bad)}. "
                 f"Choose from: {', '.join(LABEL_CHOICES)}")
    templates = [LABEL_CHOICES[w] for w in wanted]
    if not templates:
        sys.exit("Error: --labels selected nothing to print")

    from greenlight.shopify_client import get_draft_order_by_name
    order = get_draft_order_by_name(args.order)
    if not order:
        sys.exit(f"Error: no draft order named {args.order!r}. "
                 f"Try --list to see what's there.")

    customer = (order.get("customer") or {}).get("displayName") or "?"
    print()
    print(f"  Order:    {order['name']}  ({order.get('status', '')})")
    print(f"  Customer: {customer}")
    print()

    plan = plan_order(order["line_items"], templates=templates,
                      upc_by_sku=resolve_upcs(templates))

    for line in describe_plan(plan):
        print("  " + line)
    if plan.warnings:
        print()
        for w in plan.warnings:
            print(f"  !! {w}")
    print()

    if not plan.jobs:
        print("  Nothing to print.\n")
        return 1
    if args.preview:
        return 0

    if args.mock:
        print("  Using MOCK printers (no actual hardware)")
    printers = build_label_printers(mock=args.mock)

    # One pass per printer. A failure on one doesn't stop the other.
    ok = True
    for stock, jobs in sorted(plan.by_stock.items(), key=lambda kv: kv[0][1]):
        inches = f'{stock[0] / 25.4:.0f}" x {stock[1] / 25.4:.0f}"'
        total = sum(j.quantity for j in jobs)
        print()
        print(f"  --- {inches} printer: {total} label(s) in {len(jobs)} job(s)")

        printer = printers.get(stock)
        if printer is None:
            print("      FAILED: no printer configured for this stock")
            ok = False
            continue
        if not printer.initialize():
            print(f"      FAILED: can't reach the printer at {printer.ip_address}")
            ok = False
            continue

        for job in jobs:
            data = dict(job.data)
            data["label_width_mm"], data["label_height_mm"] = stock
            if not printer.print_labels(PrintJob(
                    template=job.template, data=data, quantity=job.quantity)):
                print(f"      FAILED: {job.quantity} x {job.sku} "
                      f"{job.label_name}")
                ok = False
                break
            print(f"      sent {job.quantity:3} x {job.sku:14} "
                  f"{job.label_name}")
        printer.close()

    print()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
