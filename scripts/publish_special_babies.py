#!/usr/bin/env python3
"""Ensure all special baby Shopify products are published to all sales channels.

Fetches all Shopify products, filters to Special Baby product type, checks
which sales channels each is published to, and publishes to any missing channels.

Usage:
    source dev_env.sh
    python scripts/publish_special_babies.py          # dry-run (default)
    python scripts/publish_special_babies.py --apply   # actually publish
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shopify
from greenlight.shopify_client import (
    get_shopify_session, close_shopify_session,
    _get_publication_ids, _publish_product_to_all_channels,
    get_all_product_skus,
)


def get_product_publications(product_id):
    """Get the set of publication IDs a product is currently published to."""
    session = get_shopify_session()
    try:
        query = """
        query getProductPublications($id: ID!) {
            product(id: $id) {
                resourcePublicationsV2(first: 20) {
                    edges {
                        node {
                            publication { id }
                            isPublished
                        }
                    }
                }
            }
        }
        """
        result = shopify.GraphQL().execute(query, variables={"id": product_id})
        data = json.loads(result)

        if "errors" in data:
            print(f"  GraphQL errors: {data['errors']}")
            return set()

        edges = (data.get("data", {}).get("product", {})
                 .get("resourcePublicationsV2", {}).get("edges", []))
        return {
            edge["node"]["publication"]["id"]
            for edge in edges
            if edge["node"].get("isPublished")
        }
    finally:
        close_shopify_session()


def main():
    parser = argparse.ArgumentParser(
        description="Publish special baby products to all sales channels"
    )
    parser.add_argument("--apply", action="store_true",
                        help="Actually publish (default is dry-run)")
    args = parser.parse_args()

    print("Fetching all Shopify products...")
    all_skus = get_all_product_skus()
    print(f"  {len(all_skus)} total SKUs")

    # Filter to special babies
    special_babies = {
        sku: info for sku, info in all_skus.items()
        if info.get("product_type") == "Special Baby"
    }
    print(f"  {len(special_babies)} Special Baby products")

    # Get all sales channel IDs
    all_pub_ids = set(_get_publication_ids())
    if not all_pub_ids:
        print("ERROR: Could not fetch publication IDs")
        return 1
    print(f"  {len(all_pub_ids)} sales channels")
    print()

    # Dedupe by product_id (multiple variants could share a product)
    products = {}
    for sku, info in special_babies.items():
        pid = info["product_id"]
        if pid not in products:
            products[pid] = {
                "sku": sku,
                "title": info.get("product_title", ""),
                "status": info.get("status", ""),
            }

    already_ok = 0
    needs_publish = 0
    published = 0
    errors = 0

    for product_id, info in sorted(products.items(), key=lambda x: x[1]["sku"]):
        sku = info["sku"]
        title = info["title"]
        status = info["status"]

        current_pubs = get_product_publications(product_id)
        missing = all_pub_ids - current_pubs

        if not missing:
            already_ok += 1
            continue

        needs_publish += 1

        if args.apply:
            ok = _publish_product_to_all_channels(product_id)
            if ok:
                print(f"  OK   {sku:22s}  [{status}] {title}  (+{len(missing)} channels)")
                published += 1
            else:
                print(f"  ERR  {sku:22s}  [{status}] {title}")
                errors += 1
        else:
            print(f"  DRY  {sku:22s}  [{status}] {title}  (missing {len(missing)}/{len(all_pub_ids)} channels)")

    # Summary
    print(f"\n{'=' * 60}")
    mode = "APPLIED" if args.apply else "DRY RUN"
    print(f"  {mode}:")
    print(f"    Already published:  {already_ok}")
    print(f"    Needed publishing:  {needs_publish}")
    if args.apply:
        print(f"    Published:          {published}")
        print(f"    Errors:             {errors}")

    if not args.apply and needs_publish > 0:
        print(f"\n  Re-run with --apply to publish.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
