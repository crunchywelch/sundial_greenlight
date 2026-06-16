/**
 * Custom Cable Sets configurator — catalog + pricing.
 *
 * This is the single source of truth for the customer-facing custom-run
 * configurator served at the App Proxy `/apps/custom-cables`. It is
 * deliberately DECOUPLED from the SKU resolver (cable-config.server.js):
 * custom runs are quotes, not catalog SKUs, so the option universe here is
 * broader (any pattern, any color, free-form length) and isn't tied to
 * sku_group identity or inventory.
 *
 * Pricing model comes straight from custom_cable_sets_page.md:
 *
 *   $5 per foot of cable  +  $10 per finished cable (connectors)
 *   Minimum order: 100 ft of total cable per run.
 *
 * Per finished cable that works out to:  length_ft * $5 + $10
 * which folds cleanly into a single draft-order line item per (length,
 * quantity) row — see proxy.custom-cables.submit.jsx.
 *
 * Editing the catalog below changes what customers can pick. It does NOT
 * touch the database or the catalog SKU machinery.
 */

// ---------------------------------------------------------------------------
// Pricing constants (USD). Authoritative — the page embeds these for the live
// preview and the submit action recomputes from them server-side.
// ---------------------------------------------------------------------------
export const PRICING = {
  perFoot: 5,
  perCable: 10,
  minTotalFeet: 100,
  currency: "USD",
};

// ---------------------------------------------------------------------------
// Option catalog. Merchant-editable. `value` is the stable key stored on the
// draft order; `label` is what the customer sees.
//
// Colors are keyed by fabric (rayon / cotton) — the available swatches differ
// between the two, and the form repopulates the color dropdowns when the
// customer switches fabric. A free-form "color notes" field covers anything
// off-list. FABRICS keys must match the COLORS keys below.
// ---------------------------------------------------------------------------
// `image` is an optional thumbnail shown when the pattern is selected. Paste a
// Shopify Files CDN URL (Admin → Content → Files → copy link), e.g.
// "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/xxxx.jpg?v=...".
// Leave it "" to show no thumbnail for that pattern.
export const PATTERNS = [
  { value: "solid", label: "Solid Color", colors: 1, image: "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/20260222_195707.jpg?v=1771951232", note: "A single-hue braid that lets your color choice carry the look." },
  { value: "small-houndstooth", label: "Small Houndstooth", colors: 2, image: "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/20260223_172618.jpg?v=1771950789", note: "A subtle woven check that adds texture without shouting." },
  { value: "large-houndstooth", label: "Large Houndstooth", colors: 2, image: "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/20260224_110258.jpg?v=1771950816", note: "A subtle woven check that adds texture without shouting." },
  { value: "tracer", label: "Tracer", colors: 2, image: "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/20260222_194658.jpg?v=1771951207", note: "Classic braid with a contrasting stripe woven in." },
  { value: "double-tracer", label: "Double Tracer", colors: 3, image: "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/20251217_133042.jpg?v=1765996692", note: "Classic braid with two contrasting stripes woven in." },
  { value: "zig-zag", label: "Zig-Zag", colors: 2, image: "https://cdn.shopify.com/s/files/1/0674/1475/3363/files/20251217_124303.jpg?v=1765996705", note: "A bold, high-movement pattern that stands out on any stage." },
];

export const FABRICS = [
  { value: "cotton", label: "Cotton" },
  { value: "rayon", label: "Rayon" },
];

const toColors = (names) =>
  names.map((name) => ({ value: name.toLowerCase().replace(/\s+/g, "-"), label: name }));

export const COLORS = {
  rayon: toColors([
    "Gold", "Walnut Brown", "Pewter", "White", "Mahogany Brown", "Black",
    "Plata", "Silver",
  ]),
  cotton: toColors([
    "Gray", "Dark Brown", "Bleach White", "Yellow", "Burnt Orange",
    "Lime Green", "Slate Blue", "Raspberry", "Black", "Light Brown",
    "Putty", "Brush Gold", "Red", "Bright Gold", "Green", "Turquoise",
  ]),
};

/**
 * Resolve a color value to its display label across all fabrics. Used by the
 * submit action, where the chosen fabric is already known but a flat lookup
 * keeps it simple (a value like "black" exists under both fabrics with the
 * same label). Falls back to the raw value if unknown.
 */
export function colorLabel(value) {
  for (const fabric of Object.keys(COLORS)) {
    const hit = COLORS[fabric].find((c) => c.value === value);
    if (hit) return hit.label;
  }
  return value || "—";
}

// Cable type drives which connector options apply.
export const CABLE_TYPES = [
  {
    value: "instrument",
    label: "Instrument",
    connectors: [
      { value: "ts-ts", label: "Straight / Straight (TS–TS)" },
      { value: "ra-ts", label: "Straight / Right-angle (RA–TS)" },
    ],
  },
  {
    value: "microphone",
    label: "Microphone",
    connectors: [{ value: "xlr-xlr", label: "XLR–XLR" }],
  },
];

/**
 * The whole catalog as a plain object, for embedding in the page as JSON so
 * the client renders the same options and computes the same live preview.
 */
export function configCatalog() {
  return { pricing: PRICING, patterns: PATTERNS, fabrics: FABRICS, colors: COLORS, cableTypes: CABLE_TYPES };
}

// ---------------------------------------------------------------------------
// Pricing. Pure — no I/O. Unit-tested in tests/custom-quote.test.js.
// ---------------------------------------------------------------------------

/** Price for one finished cable of `lengthFt`: length * perFoot + perCable. */
export function unitPrice(lengthFt) {
  return lengthFt * PRICING.perFoot + PRICING.perCable;
}

/**
 * Quote a custom set. `lines` is [{ lengthFt, quantity }, ...].
 *
 * Returns:
 *   { lines: [{ lengthFt, quantity, unitPrice, lineTotal, lineFeet }],
 *     totalFeet, totalCables, cableCost, connectorCost, total,
 *     meetsMinimum, minTotalFeet }
 *
 * `cableCost` / `connectorCost` break the total out the way the pricing
 * table in custom_cable_sets_page.md presents it. `total` equals their sum
 * and equals Σ unitPrice*quantity.
 *
 * Throws RangeError on malformed input (non-positive length/quantity).
 */
export function quoteCustomSet(lines) {
  if (!Array.isArray(lines) || lines.length === 0) {
    throw new RangeError("At least one length/quantity line is required");
  }

  const priced = lines.map((line, i) => {
    const lengthFt = Number(line.lengthFt);
    const quantity = Number(line.quantity);
    if (!Number.isFinite(lengthFt) || lengthFt <= 0) {
      throw new RangeError(`Line ${i + 1}: length must be a positive number`);
    }
    if (!Number.isInteger(quantity) || quantity <= 0) {
      throw new RangeError(`Line ${i + 1}: quantity must be a positive integer`);
    }
    const u = unitPrice(lengthFt);
    return {
      lengthFt,
      quantity,
      unitPrice: u,
      lineTotal: u * quantity,
      lineFeet: lengthFt * quantity,
    };
  });

  const totalFeet = priced.reduce((s, l) => s + l.lineFeet, 0);
  const totalCables = priced.reduce((s, l) => s + l.quantity, 0);
  const cableCost = totalFeet * PRICING.perFoot;
  const connectorCost = totalCables * PRICING.perCable;

  return {
    lines: priced,
    totalFeet,
    totalCables,
    cableCost,
    connectorCost,
    total: cableCost + connectorCost,
    meetsMinimum: totalFeet >= PRICING.minTotalFeet,
    minTotalFeet: PRICING.minTotalFeet,
  };
}
