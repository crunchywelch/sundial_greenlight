/**
 * LTD edition constants and pure helpers safe to import from both server
 * (loaders/actions) and client (route components). No DB or server-only
 * dependencies belong here — anything imported from `editions.server.js`
 * gets stripped from the client bundle.
 */

export const SLUG_PATTERN = /^[A-Z0-9]{4,12}$/;

/** Parse an LTD SKU into { prefix, slug } or null if it doesn't match. */
export function parseLtdSku(sku) {
  const m = sku && sku.match(/^([A-Z]+)-LTD-([A-Z0-9]{4,12})$/);
  if (!m) return null;
  return { prefix: m[1], slug: m[2] };
}
