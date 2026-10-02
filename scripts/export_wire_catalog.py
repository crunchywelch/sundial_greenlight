#!/usr/bin/env python3
"""Export the Sundial Wire Shopify catalog for an InDesign Data Merge.

Pulls every product (and variant) from the Sundial Wire store, downloads the
featured image for each product, computes a wholesale price as a percentage off
retail, and writes a Data-Merge-ready CSV.

InDesign Data Merge conventions honored here:
  - First CSV row is the field names (used as placeholder names in InDesign).
  - The image column header is prefixed with ``@`` so InDesign treats the cell
    value as a path to an image to place.
  - Image cells contain paths relative to the CSV file (so the CSV + images/
    folder can be moved together, and Windows/WSL path prefixes don't matter).

Usage:
    python -m scripts.export_wire_catalog                # 50% off, all products
    python -m scripts.export_wire_catalog --discount 40  # 40% off retail
    python -m scripts.export_wire_catalog --active-only   # skip drafts/archived
    python -m scripts.export_wire_catalog --by variant    # one row per SKU

Output (under data/wire_catalog/ by default):
    catalog.csv          the Data Merge source file
    images/<handle>.jpg  one downloaded featured image per product
"""

import argparse
import csv
import json
import logging
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import requests

from greenlight import shopify_client
import shopify

logger = logging.getLogger("export_wire_catalog")

PRODUCTS_QUERY = """
query getProducts($limit: Int!, $cursor: String) {
    products(first: $limit, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        edges {
            node {
                id
                title
                handle
                productType
                vendor
                status
                description
                tags
                featuredImage { url altText }
                variants(first: 100) {
                    edges {
                        node {
                            sku
                            title
                            price
                            inventoryQuantity
                            barcode
                        }
                    }
                }
            }
        }
    }
}
"""


def fetch_all_products(limit: int = 250) -> list[dict]:
    """Paginate the Wire store and return raw product nodes."""
    shopify_client.get_wire_shopify_session()
    try:
        products, cursor, has_next = [], None, True
        while has_next:
            result = shopify.GraphQL().execute(
                PRODUCTS_QUERY, variables={"limit": limit, "cursor": cursor}
            )
            data = json.loads(result)
            if "errors" in data:
                raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")
            block = data.get("data", {}).get("products", {})
            products.extend(edge["node"] for edge in block.get("edges", []))
            page = block.get("pageInfo", {})
            has_next = page.get("hasNextPage", False)
            cursor = page.get("endCursor")
        return products
    finally:
        shopify_client.close_shopify_session()


def wholesale_price(retail: str, discount_pct: float) -> str:
    """Return retail * (1 - discount) as a 2-decimal string, or '' if no price."""
    if not retail:
        return ""
    try:
        factor = Decimal(1) - (Decimal(str(discount_pct)) / Decimal(100))
        value = (Decimal(retail) * factor).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return f"{value}"
    except Exception:
        return ""


def download_image(url: str, dest: Path) -> bool:
    """Download an image URL to dest. Returns True on success."""
    if not url:
        return False
    if dest.exists():
        return True
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        logger.warning("Could not download image %s: %s", url, e)
        return False


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "product"


def _image_ext(url: str) -> str:
    m = re.search(r"\.(jpg|jpeg|png|gif|webp)(?:\?|$)", url or "", re.IGNORECASE)
    return f".{m.group(1).lower()}" if m else ".jpg"


def build_rows(products: list[dict], discount_pct: float, by: str,
               active_only: bool, out_dir: Path, images_dir: Path) -> list[dict]:
    """Flatten product nodes into CSV rows, downloading images as we go."""
    rows = []
    for p in products:
        if active_only and p.get("status") != "ACTIVE":
            continue

        handle = p.get("handle") or _slug(p.get("title"))
        img = p.get("featuredImage") or {}
        img_url = img.get("url", "")
        img_path = ""
        if img_url:
            dest = images_dir / f"{handle}{_image_ext(img_url)}"
            if download_image(img_url, dest):
                # Relative to the CSV so InDesign resolves it locally on any OS.
                img_path = dest.relative_to(out_dir).as_posix()

        variants = [e["node"] for e in p.get("variants", {}).get("edges", [])]
        prices = [v.get("price") for v in variants if v.get("price")]

        def _min_max(price_strs):
            """Numeric min/max returned as original strings (e.g. '9.00', '10.00')."""
            if not price_strs:
                return "", ""
            ranked = sorted(price_strs, key=lambda s: Decimal(s))
            return ranked[0], ranked[-1]

        base = {
            "Title": p.get("title", ""),
            "Description": (p.get("description") or "").strip(),
            "ProductType": p.get("productType", ""),
            "Vendor": p.get("vendor", ""),
            "Tags": ", ".join(p.get("tags", []) or []),
            "Handle": handle,
            "@Image": img_path,
        }

        if by == "variant":
            for v in variants:
                retail = v.get("price", "")
                rows.append({
                    **base,
                    "SKU": v.get("sku", ""),
                    "VariantTitle": v.get("title", ""),
                    "Barcode": v.get("barcode") or "",
                    "Inventory": v.get("inventoryQuantity", ""),
                    "RetailPrice": retail,
                    "WholesalePrice": wholesale_price(retail, discount_pct),
                })
        else:  # one row per product; show a price range for multi-variant items
            lo, hi = _min_max(prices)
            retail = lo if lo == hi else f"{lo}–{hi}"
            rows.append({
                **base,
                "SKU": variants[0].get("sku", "") if variants else "",
                "VariantCount": len(variants),
                "RetailPrice": retail,
                "WholesalePrice": (
                    wholesale_price(lo, discount_pct) if lo == hi
                    else f"{wholesale_price(lo, discount_pct)}–{wholesale_price(hi, discount_pct)}"
                ),
            })
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        raise SystemExit("No products to export.")
    # Preserve a sensible column order: @Image first is handy in InDesign.
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--discount", type=float, default=50.0,
                    help="Wholesale discount percent off retail (default: 50)")
    ap.add_argument("--by", choices=["product", "variant"], default="product",
                    help="One row per product (default) or per variant/SKU")
    ap.add_argument("--active-only", action="store_true",
                    help="Skip draft/archived products")
    ap.add_argument("--out", type=Path, default=Path("data/wire_catalog"),
                    help="Output directory (default: data/wire_catalog)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    out_dir = args.out
    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Fetching products from Sundial Wire store...")
    products = fetch_all_products()
    logger.info("Fetched %d products. Building rows / downloading images...", len(products))

    rows = build_rows(products, args.discount, args.by, args.active_only, out_dir, images_dir)
    csv_path = out_dir / "catalog.csv"
    write_csv(rows, csv_path)

    logger.info("Wrote %d rows to %s", len(rows), csv_path)
    logger.info("Images in %s", images_dir)
    logger.info("Wholesale = retail - %.1f%%. Open the CSV in InDesign via "
                "Window > Utilities > Data Merge.", args.discount)


if __name__ == "__main__":
    main()
