#!/usr/bin/env python3
"""
Scheduled catalog sync for the cordset configurator.

Live-fetches Sundial Wire products (read-only GraphQL), builds the cordset
catalog, folds in Ian's verified compatibility overrides if present, and writes
cordsets.catalog.json — the artifact the configurator form and Sparky read.

Run on a schedule (nightly) and on demand. Shopify stays authoritative for
price/stock at checkout because the form adds real variants to the cart; this
cache just drives the option universe + verified compatibility.

    venv/bin/python util/wire/cordset/sync_catalog.py
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session
from util.wire.cordset.derive_catalog import build_catalog, print_diagnostics

D = Path(__file__).parent

PRODUCTS_QUERY = """
query all($limit: Int!, $cursor: String) {
  products(first: $limit, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id handle title status productType vendor tags
      featuredImage { url }
      options { name values }
      collections(first: 10) { edges { node { handle } } }
      variants(first: 100) { edges { node {
        id sku price selectedOptions { name value } inventoryQuantity
        image { url }
      } } }
    } }
  }
}
"""


def fetch_products():
    items, cursor, has_next = [], None, True
    while has_next:
        raw = shopify.GraphQL().execute(PRODUCTS_QUERY, variables={"limit": 250, "cursor": cursor})
        data = json.loads(raw)
        if "errors" in data:
            raise RuntimeError(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
        conn = data["data"]["products"]
        items.extend(e["node"] for e in conn["edges"])
        has_next = conn["pageInfo"]["hasNextPage"]
        cursor = conn["pageInfo"]["endCursor"]
        print(f"  ...fetched {len(items)} products")
    return items


def main():
    get_wire_shopify_session()
    try:
        products = fetch_products()
    finally:
        close_shopify_session()

    ov_path = D / "compat_overrides.json"
    overrides = json.loads(ov_path.read_text()) if ov_path.exists() else None

    catalog, diag = build_catalog(products, overrides)
    (D / "cordsets.catalog.json").write_text(json.dumps(catalog, indent=2))

    print_diagnostics(diag)
    print("compat source:", catalog["compatSource"])
    print("wrote cordsets.catalog.json")


if __name__ == "__main__":
    main()
