import { json } from "@remix-run/node";
import { query } from "../db.server.js";
import { parseGroupSku, seriesForPrefix, seriesDataForPrefix, formatVariantSku } from "../cable-config.server.js";

const APP_URL = "https://greenlight.sundialwire.com";
const ADMIN_API_VERSION = "2026-07";

// Fallback product photos hosted by this app. Real images come from the Shopify
// CDN (resolved by variant SKU below); these are only used when Shopify has no
// image for a variant — e.g. Shopify is unreachable, or a special-edition
// product hasn't been created yet. Unknown pattern → no image at all.
const CABLE_IMAGE_MAP = {
  "goldline": "cable-goldline.png",
  "pearl white": "cable-pearl-white.png",
  "silverline": "cable-silverline.png",
  "bungalow": "cable-bungalow.png",
  "electric houndstooth": "cable-electric-houndstooth.png",
  "houndstooth putty": "cable-houndstooth-putty.png",
  "road stripe": "cable-road-stripe.png",
};

function curatedImageUrl(colorPattern) {
  const file = CABLE_IMAGE_MAP[(colorPattern || "").toLowerCase()];
  return file ? `${APP_URL}/images/${file}` : null;
}

// Cache Shopify product images by variant SKU so we don't hit the Admin API on
// every page load. Found images are cached longer; misses (e.g. a special
// edition whose Shopify product doesn't exist yet) expire quickly so a newly
// created product shows up soon after.
const imageCache = new Map(); // sku -> { url: string|null, expires: number }
const FOUND_TTL_MS = 6 * 60 * 60 * 1000;
const MISS_TTL_MS = 15 * 60 * 1000;

export async function loader({ request }) {
  const url = new URL(request.url);
  const customerId = url.searchParams.get("customerId");

  if (!customerId) {
    return json({ error: "Customer ID is required" }, { status: 400 });
  }

  const gid = customerId.startsWith("gid://")
    ? customerId
    : `gid://shopify/Customer/${customerId}`;

  try {
    const cables = await fetchCustomerCables(gid);
    return json({ cables });
  } catch (error) {
    console.error("Error fetching customer cables:", error);
    return json({ error: "Failed to fetch cables" }, { status: 500 });
  }
}

async function fetchCustomerCables(customerId) {
  const result = await query(
    `SELECT
      ac.serial_number,
      ac.sku_group,
      ac.prefix,
      ac.length,
      ac.connector_code,
      ac.test_passed,
      ac.test_timestamp,
      ac.operator,
      ac.shopify_gid,
      sg.description
    FROM audio_cables ac
    LEFT JOIN sku_group sg ON sg.sku = ac.sku_group
    WHERE ac.shopify_gid = $1
    ORDER BY ac.test_timestamp DESC NULLS LAST`,
    [customerId]
  );

  const cables = result.rows.map((row) => {
    const parsed = parseGroupSku(row.sku_group);
    const seriesData = seriesDataForPrefix(row.prefix);
    const connectorDisplay =
      seriesData?.connectors?.find((c) => (c.code ?? "") === (row.connector_code ?? ""))?.display ?? null;
    const variantSku = formatVariantSku({
      prefix: row.prefix,
      group_sku: row.sku_group,
      length: Number(row.length),
      connector_code: row.connector_code,
    });
    const colorPattern = parsed.pattern_name ?? null;
    return {
      serial_number: row.serial_number,
      sku: variantSku,
      sku_group: row.sku_group,
      prefix: row.prefix,
      kind: parsed.kind,
      series: seriesForPrefix(row.prefix),
      color: colorPattern,
      connector_type: connectorDisplay,
      core_cable: seriesData?.core_cable ?? null,
      length: Number(row.length),
      description: row.description,
      test_date: row.test_timestamp,
      test_passed: row.test_passed,
      test_status: row.test_passed !== null ? "tested" : "not tested",
      operator: row.operator,
      image: null,
    };
  });

  // Resolve real product images from Shopify by variant SKU, falling back to a
  // curated photo (or nothing) when Shopify has no image for the variant.
  const skus = [...new Set(cables.map((c) => c.sku).filter(Boolean))];
  const imagesBySku = await fetchProductImages(skus);
  for (const cable of cables) {
    cable.image = imagesBySku.get(cable.sku) ?? curatedImageUrl(cable.color);
  }

  return cables;
}

// Look up Shopify product images for a set of variant SKUs. Returns a
// Map<sku, url|null>. Never throws — image resolution is best-effort and must
// not break the cables list.
async function fetchProductImages(skus) {
  const out = new Map();
  const now = Date.now();
  const misses = [];
  for (const sku of skus) {
    const hit = imageCache.get(sku);
    if (hit && hit.expires > now) out.set(sku, hit.url);
    else misses.push(sku);
  }
  if (misses.length === 0) return out;

  let session;
  try {
    const res = await query(
      `SELECT shop, access_token FROM shopify_sessions
       WHERE is_online = false AND access_token IS NOT NULL LIMIT 1`
    );
    session = res.rows[0];
  } catch (err) {
    console.error("Could not load Shopify session for image lookup:", err);
    session = null;
  }

  if (!session) {
    // Can't resolve right now; don't cache so we retry on the next request.
    for (const sku of misses) out.set(sku, null);
    return out;
  }

  const { shop, access_token } = session;
  const gql = `query ProductImages($q: String!) {
    productVariants(first: 250, query: $q) {
      nodes { sku image { url } product { featuredImage { url } } }
    }
  }`;

  const CHUNK = 40;
  for (let i = 0; i < misses.length; i += CHUNK) {
    const chunk = misses.slice(i, i + CHUNK);
    const searchQuery = chunk.map((sku) => `sku:${sku}`).join(" OR ");
    const found = new Map();
    try {
      const resp = await fetch(
        `https://${shop}/admin/api/${ADMIN_API_VERSION}/graphql.json`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": access_token,
          },
          body: JSON.stringify({ query: gql, variables: { q: searchQuery } }),
        }
      );
      const data = await resp.json();
      for (const node of data?.data?.productVariants?.nodes ?? []) {
        // Prefer a variant-specific image, else the product's featured image.
        const imgUrl = node.image?.url ?? node.product?.featuredImage?.url ?? null;
        if (node.sku) found.set(node.sku, imgUrl);
      }
    } catch (err) {
      console.error("Shopify product image lookup failed:", err);
      // Treat as misses without caching so we retry later.
      for (const sku of chunk) out.set(sku, null);
      continue;
    }
    for (const sku of chunk) {
      const imgUrl = found.get(sku) ?? null;
      imageCache.set(sku, {
        url: imgUrl,
        expires: now + (imgUrl ? FOUND_TTL_MS : MISS_TTL_MS),
      });
      out.set(sku, imgUrl);
    }
  }

  return out;
}
