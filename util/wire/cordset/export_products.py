#!/usr/bin/env python3
"""
READ-ONLY export of Sundial Wire products, for building the cordset
configurator catalog / compatibility matrix.

Runs only GraphQL *queries* against the Wire store — no mutations. Dumps raw
JSON next to this script and prints bucket histograms so we can see how
cordsets and their components (plugs/sockets/switches/wire) are structured.

Usage (from repo root, SHOPIFY_WIRE_* populated in .env):
    venv/bin/python util/wire/cordset/export_products.py
"""

import sys
import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import shopify
from greenlight.shopify_client import get_wire_shopify_session, close_shopify_session

OUT_DIR = Path(__file__).parent
EXAMPLE_PRODUCT_GID = "gid://shopify/Product/4159620251712"


def gql(query, variables=None):
    raw = shopify.GraphQL().execute(query, variables=variables or {})
    data = json.loads(raw)
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
    return data["data"]


EXAMPLE_QUERY = """
query one($id: ID!) {
  product(id: $id) {
    id handle title status productType vendor tags
    description
    options { name values }
    collections(first: 20) { edges { node { handle title } } }
    metafields(first: 50) { edges { node { namespace key type value } } }
    variants(first: 100) {
      edges { node {
        id title sku price
        selectedOptions { name value }
        inventoryQuantity
        inventoryItem { unitCost { amount } }
      } }
    }
  }
}
"""

ALL_QUERY = """
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


def fetch_all():
    items, cursor, has_next = [], None, True
    while has_next:
        data = gql(ALL_QUERY, {"limit": 250, "cursor": cursor})
        conn = data["products"]
        for edge in conn["edges"]:
            items.append(edge["node"])
        has_next = conn["pageInfo"]["hasNextPage"]
        cursor = conn["pageInfo"]["endCursor"]
        print(f"  ...fetched {len(items)} products so far")
    return items


def flatten_edges(node, key):
    return [e["node"] for e in node.get(key, {}).get("edges", [])]


def main():
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    get_wire_shopify_session()

    print("Fetching example product...")
    example = gql(EXAMPLE_QUERY, {"id": EXAMPLE_PRODUCT_GID})["product"]
    (OUT_DIR / "cordset_example.json").write_text(json.dumps(example, indent=2))
    print(f"  -> wrote cordset_example.json ({example.get('title')!r})")

    print("Fetching all products...")
    products = fetch_all()
    (OUT_DIR / "wire_products_all.json").write_text(json.dumps(products, indent=2))
    print(f"  -> wrote wire_products_all.json ({len(products)} products)")

    types = Counter(p.get("productType") or "(none)" for p in products)
    tags = Counter(t for p in products for t in (p.get("tags") or []))
    opt_names = Counter(o["name"] for p in products for o in (p.get("options") or []))
    collections = Counter(
        c["handle"] for p in products for c in flatten_edges(p, "collections")
    )

    def show(title, counter, n=40):
        print(f"\n=== {title} (top {n}) ===")
        for k, v in counter.most_common(n):
            print(f"  {v:5d}  {k}")

    show("productType", types)
    show("tags", tags)
    show("option names", opt_names)
    show("collections", collections)

    close_shopify_session()
    print("\nDone. JSON dumps are in:", OUT_DIR)


if __name__ == "__main__":
    main()
