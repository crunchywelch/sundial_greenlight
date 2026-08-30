/**
 * Backend broker for the B2B wholesale reorder form (customer account extension).
 *
 * A customer-account UI extension cannot read B2B/market-catalog prices or build
 * a B2B cart on its own (its Storefront token is unauthenticated, public-catalog
 * only). So the extension sends its session token + companyLocationId here, and
 * this module verifies the token, confirms the customer may buy for that
 * location, and resolves the wholesale catalog + prices via the Admin API.
 *
 * Pricing note: the store is on Grow (market-based B2B catalogs), so we read each
 * variant's `contextualPricing(companyLocationId)` (the price the buyer actually
 * pays) rather than walking a per-company catalog. MSRP is the variant's own price.
 */
import crypto from "node:crypto";
import { query } from "./db.server.js";

const ADMIN_API_VERSION = "2026-07";

// The dealer sheet sells these lengths only; Shopify also has a "1' patch"
// variant we deliberately omit.
export const ALLOWED_LENGTHS = [3, 6, 10, 12, 15, 20, 25];

// Shopify's "Plugs" option value -> our compact connector code + sheet label.
// Some products list the words in a different order, so match loosely.
const CONNECTORS = [
  { code: "ss", label: "TS-S/S", match: (v) => /straight\s*\/\s*straight/i.test(v) },
  { code: "sr", label: "TS-S/R", match: (v) => /straight\s*\/\s*right\s*angle/i.test(v) },
  { code: "xlr", label: "XLR", match: (v) => /xlr/i.test(v) },
];
export const CONNECTOR_COLUMNS = CONNECTORS.map(({ code, label }) => ({ code, label }));

// Series subtitle text mirrors the dealer sheet section headers.
const SERIES_SUBTITLE = {
  "Studio Series": "Rayon braid with gold/black Neutrik connectors",
  "Touring Series": "Cotton braid with nickel Neutrik connectors",
};
const SERIES_ORDER = ["Studio Series", "Touring Series"];

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
export { HttpError };

// --- Auth: verify the customer-account extension session token ------------

function base64urlToBuffer(s) {
  return Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

/**
 * Verify the Bearer session token a customer-account extension sends. It's an
 * HS256 JWT signed with the app's client secret, audience = the app's client id.
 * Returns { customerId } (the `sub` claim, a Customer GID; present because the
 * app holds read_customers). Throws HttpError(401) on any failure.
 */
export function verifyCustomerAccountToken(request) {
  const header = request.headers.get("Authorization") || "";
  const token = header.replace(/^Bearer\s+/i, "").trim();
  if (!token) throw new HttpError(401, "Missing session token");

  const parts = token.split(".");
  if (parts.length !== 3) throw new HttpError(401, "Malformed session token");
  const [h, p, sig] = parts;

  const secret = process.env.SHOPIFY_API_SECRET || "";
  const expected = crypto
    .createHmac("sha256", secret)
    .update(`${h}.${p}`)
    .digest("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
  const got = Buffer.from(sig);
  const want = Buffer.from(expected);
  if (got.length !== want.length || !crypto.timingSafeEqual(got, want)) {
    throw new HttpError(401, "Invalid session token signature");
  }

  let payload;
  try {
    payload = JSON.parse(base64urlToBuffer(p).toString("utf8"));
  } catch {
    throw new HttpError(401, "Invalid session token payload");
  }

  const now = Math.floor(Date.now() / 1000);
  if (payload.exp && now >= payload.exp) throw new HttpError(401, "Session token expired");
  if (payload.nbf && now < payload.nbf - 5) throw new HttpError(401, "Session token not yet valid");

  const apiKey = process.env.SHOPIFY_API_KEY;
  if (apiKey && payload.aud !== apiKey) throw new HttpError(401, "Session token audience mismatch");

  const customerId = payload.sub;
  if (!customerId) throw new HttpError(401, "Session token missing customer");
  return { customerId };
}

// --- Admin API access via the stored offline token ------------------------

async function getOfflineSession() {
  const res = await query(
    `SELECT shop, access_token FROM shopify_sessions
     WHERE is_online = false AND access_token IS NOT NULL LIMIT 1`
  );
  const row = res.rows[0];
  if (!row) throw new HttpError(503, "Shopify session unavailable");
  return { shop: row.shop, accessToken: row.access_token };
}

async function adminGraphql(gql, variables) {
  const { shop, accessToken } = await getOfflineSession();
  const resp = await fetch(`https://${shop}/admin/api/${ADMIN_API_VERSION}/graphql.json`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Shopify-Access-Token": accessToken,
    },
    body: JSON.stringify({ query: gql, variables }),
  });
  const data = await resp.json();
  if (data.errors) {
    console.error("Admin GraphQL errors:", JSON.stringify(data.errors));
    throw new HttpError(502, "Shopify request failed");
  }
  return data.data;
}

/**
 * Confirm the authenticated customer is a contact who may purchase for the given
 * company location. Prevents a caller from pulling another company's pricing or
 * ordering against a location that isn't theirs.
 */
export async function assertCustomerOwnsLocation(customerId, companyLocationId) {
  const data = await adminGraphql(
    `#graphql
    query ownedLocations($id: ID!) {
      customer(id: $id) {
        companyContactProfiles {
          roleAssignments(first: 50) {
            nodes { companyLocation { id } }
          }
        }
      }
    }`,
    { id: customerId }
  );
  const owned = new Set();
  for (const profile of data.customer?.companyContactProfiles ?? []) {
    for (const ra of profile.roleAssignments?.nodes ?? []) {
      if (ra.companyLocation?.id) owned.add(ra.companyLocation.id);
    }
  }
  if (!owned.has(companyLocationId)) {
    throw new HttpError(403, "Not authorized for this company location");
  }
}

// --- Catalog + wholesale pricing ------------------------------------------

function connectorCode(plugValue) {
  const hit = CONNECTORS.find((c) => c.match(plugValue));
  return hit ? hit.code : null;
}

function parseLengthFt(lengthValue) {
  const m = String(lengthValue).match(/^(\d+)\s*'/);
  return m ? parseInt(m[1], 10) : null;
}

function styleLabel(title) {
  // "Sundial Studio Classic - Pearl White" -> "Pearl White"
  const dash = title.lastIndexOf(" - ");
  return dash >= 0 ? title.slice(dash + 3).trim() : title;
}

/**
 * Build the reorder grid for a company location: the Studio + Touring styles
 * (rows), each with a cell per (length, connector) carrying the variant id, SKU,
 * MSRP and wholesale price. "Special Baby" MISC products are excluded.
 */
export async function buildWholesaleCatalog(companyLocationId) {
  const data = await adminGraphql(
    `#graphql
    query wholesaleCatalog($loc: ID!) {
      products(first: 60, query: "product_type:'Studio Series' OR product_type:'Touring Series'") {
        nodes {
          id
          title
          productType
          featuredImage { url }
          variants(first: 60) {
            nodes {
              id
              sku
              price
              selectedOptions { name value }
              contextualPricing(context: { companyLocationId: $loc }) {
                price { amount }
              }
            }
          }
        }
      }
    }`,
    { loc: companyLocationId }
  );

  const seriesMap = new Map(); // productType -> { name, subtitle, styles: [] }
  for (const product of data.products?.nodes ?? []) {
    const type = product.productType;
    if (!SERIES_SUBTITLE[type]) continue;

    const cells = {};
    for (const v of product.variants?.nodes ?? []) {
      const opts = Object.fromEntries((v.selectedOptions ?? []).map((o) => [o.name, o.value]));
      const length = parseLengthFt(opts.Length);
      const conn = connectorCode(opts.Plugs || "");
      if (length === null || !ALLOWED_LENGTHS.includes(length) || !conn) continue;

      const msrp = Number(v.price);
      const wholesaleAmount = v.contextualPricing?.price?.amount;
      const wholesale = wholesaleAmount != null ? Number(wholesaleAmount) : msrp;
      cells[`${length}|${conn}`] = { variantId: v.id, sku: v.sku, msrp, wholesale };
    }
    if (Object.keys(cells).length === 0) continue;

    if (!seriesMap.has(type)) {
      seriesMap.set(type, { name: type, subtitle: SERIES_SUBTITLE[type], styles: [] });
    }
    seriesMap.get(type).styles.push({ label: styleLabel(product.title), image: product.featuredImage?.url ?? null, cells });
  }

  const series = SERIES_ORDER.filter((t) => seriesMap.has(t)).map((t) => {
    const s = seriesMap.get(t);
    s.styles.sort((a, b) => a.label.localeCompare(b.label));
    return s;
  });

  return { lengths: ALLOWED_LENGTHS, connectors: CONNECTOR_COLUMNS, series };
}
