/**
 * Cable config resolver — single source of truth for cable attributes.
 *
 * Loads the YAML config under util/product_lines/ at module init and exposes
 * helpers to resolve series, patterns, and SKU structure. Mirrors the Python
 * resolver in greenlight/cable_config.py — both are kept honest by
 * tests/sku_fixtures.json.
 *
 * SKU model (Phase 4):
 *
 *   - sku_group: 'SC-SL', 'SC-MISC-42', 'SC-LTD-PHISH26'.
 *     This is what cable_skus.sku stores and what audio_cables.sku_group
 *     references. parseGroupSku() takes one of these.
 *
 *   - variant SKU: 'SC-12SL', 'SC-12SL-R', 'SC-MISC-42', 'SC-LTD-PHISH26'.
 *     This is the user-facing string Shopify sees in product variants and
 *     order line items. For catalog cables it embeds length and connector;
 *     for MISC/LTD it equals the group SKU. parseVariantSku() takes one of
 *     these. formatVariantSku() builds one from (sku_group, length,
 *     connector_code).
 *
 * This module is read-only on the YAML and does NOT touch the database.
 *
 * See docs/CABLE_VARIANTS_REFACTOR.md § Phase 4 for design rationale.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PRODUCT_LINES_DIR = resolve(__dirname, "..", "..", "util", "product_lines");

const SERIES_FILES = [
  "studio_classic.yaml",
  "studio_vocal.yaml",
  "tour_classic.yaml",
  "tour_vocal.yaml",
];

// Group SKU regexes
const RE_GROUP_MISC = /^([A-Z]{2,3})-MISC-(\d+)$/;
const RE_GROUP_LTD = /^([A-Z]{2,3})-LTD-([A-Z0-9]{4,12})$/;
const RE_GROUP_CATALOG = /^([A-Z]{2,3})-([A-Z]{2,3})$/;

// Variant SKU regex (catalog only — MISC/LTD variants equal their group)
const RE_VARIANT_CATALOG = /^([A-Z]{2,3})-(\d+)([A-Z]{2,3})(-R)?$/;

function loadPatterns() {
  const path = resolve(PRODUCT_LINES_DIR, "patterns.yaml");
  const data = yaml.load(readFileSync(path, "utf8"));
  const byCode = {};
  for (const p of data?.patterns || []) byCode[p.code] = p;
  return byCode;
}

function loadSeries() {
  const byPrefix = {};
  for (const fname of SERIES_FILES) {
    const path = resolve(PRODUCT_LINES_DIR, fname);
    let data;
    try {
      data = yaml.load(readFileSync(path, "utf8"));
    } catch (e) {
      console.warn(`Series YAML missing or unreadable: ${path} (${e.message})`);
      continue;
    }
    const prefix = data?.sku_prefix;
    if (!prefix) {
      console.warn(`Series YAML ${fname} has no sku_prefix; skipping`);
      continue;
    }
    byPrefix[prefix] = data;
  }
  return byPrefix;
}

const PATTERNS = loadPatterns();
const SERIES = loadSeries();

/** Return the full series name for a SKU prefix, or null if unknown. */
export function seriesForPrefix(prefix) {
  const s = SERIES[prefix];
  return s ? (s.product_line ?? null) : null;
}

/**
 * Return the full series YAML data for a prefix (product_line, core_cable,
 * braid_material, lengths[], connectors[], cost[]), or null if unknown.
 */
export function seriesDataForPrefix(prefix) {
  return SERIES[prefix] ?? null;
}

/** Return the pattern dict {code, name, fabric_type, description}, or null. */
export function patternForCode(code) {
  return PATTERNS[code] ?? null;
}

function connectorDisplay(seriesPrefix, connectorCode) {
  const s = SERIES[seriesPrefix];
  if (!s) return null;
  for (const conn of s.connectors || []) {
    if ((conn.code ?? "") === connectorCode) return conn.display ?? null;
  }
  return null;
}

/**
 * Parse a sku_group identifier into its structural components + YAML-resolved
 * names.
 *
 * Returns an object with at least `kind`. For parseable group SKUs:
 *   - 'catalog': prefix, series, pattern_code, pattern_name
 *   - 'misc':    prefix, series, misc_seq
 *   - 'ltd':     prefix, series, slug
 *
 * Unknown prefix or pattern code yields a parsed result with the unknown
 * field's resolved name as null. Truly malformed inputs return { kind: null }.
 */
export function parseGroupSku(sku) {
  if (!sku || typeof sku !== "string") return { kind: null };

  let m = sku.match(RE_GROUP_MISC);
  if (m) {
    const prefix = m[1];
    return {
      kind: "misc",
      prefix,
      series: seriesForPrefix(prefix),
      misc_seq: parseInt(m[2], 10),
    };
  }

  m = sku.match(RE_GROUP_LTD);
  if (m) {
    const [, prefix, slug] = m;
    return {
      kind: "ltd",
      prefix,
      series: seriesForPrefix(prefix),
      slug,
    };
  }

  m = sku.match(RE_GROUP_CATALOG);
  if (m) {
    const [, prefix, patternCode] = m;
    const pattern = patternForCode(patternCode);
    return {
      kind: "catalog",
      prefix,
      series: seriesForPrefix(prefix),
      pattern_code: patternCode,
      pattern_name: pattern ? (pattern.name ?? null) : null,
    };
  }

  return { kind: null };
}

/**
 * Parse a variant SKU string into structural components.
 *
 * Catalog variants ('SC-12SL', 'SC-12SL-R') decompose into group_sku, length,
 * pattern_code, connector_code. MISC and LTD variant strings equal their
 * group SKU; this function recognises them and returns kind+group_sku, with
 * length/connector fields absent.
 *
 * Returns { kind: null } on malformed input.
 */
export function parseVariantSku(sku) {
  if (!sku || typeof sku !== "string") return { kind: null };

  // MISC and LTD variants equal their group SKU
  let m = sku.match(RE_GROUP_MISC);
  if (m) {
    const prefix = m[1];
    return {
      kind: "misc",
      group_sku: sku,
      prefix,
      series: seriesForPrefix(prefix),
      misc_seq: parseInt(m[2], 10),
    };
  }

  m = sku.match(RE_GROUP_LTD);
  if (m) {
    const [, prefix, slug] = m;
    return {
      kind: "ltd",
      group_sku: sku,
      prefix,
      series: seriesForPrefix(prefix),
      slug,
    };
  }

  // Catalog variants: 'SC-12SL' or 'SC-12SL-R'
  m = sku.match(RE_VARIANT_CATALOG);
  if (m) {
    const [, prefix, lengthStr, patternCode, raSuffix] = m;
    const connectorCode = raSuffix ?? "";
    const pattern = patternForCode(patternCode);
    return {
      kind: "catalog",
      group_sku: `${prefix}-${patternCode}`,
      prefix,
      series: seriesForPrefix(prefix),
      length: parseInt(lengthStr, 10),
      pattern_code: patternCode,
      pattern_name: pattern ? (pattern.name ?? null) : null,
      connector_code: connectorCode,
      connector_display: connectorDisplay(prefix, connectorCode),
    };
  }

  return { kind: null };
}

/**
 * Build the user-facing variant SKU string from a sku_group + per-cable attrs.
 *
 * For catalog groups: '{prefix}-{length}{pattern_code}{connector_code}'.
 * For MISC/LTD groups: returns the group SKU verbatim (length/connector_code
 * are properties of the cable but don't appear in the SKU string).
 *
 * Returns null if the group_sku doesn't parse.
 */
export function formatVariantSku({ group_sku, length, connector_code }) {
  const parsed = parseGroupSku(group_sku);
  if (parsed.kind === null) return null;
  if (parsed.kind === "misc" || parsed.kind === "ltd") return group_sku;

  // catalog: need length and pattern_code
  if (length == null) return null;
  const cc = connector_code ?? "";
  return `${parsed.prefix}-${length}${parsed.pattern_code}${cc}`;
}

/** Return all known series prefixes (sorted). */
export function allPrefixes() {
  return Object.keys(SERIES).sort();
}

/** Return all known patterns (list of dicts). */
export function allPatterns() {
  return Object.values(PATTERNS);
}
