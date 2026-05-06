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

// Group SKU regexes (Phase 5 shape).
//   catalog: pattern_code only — 'GL', 'SL', 'BU'
//   ltd:     'LTD-{slug}' — series-agnostic (prefix lives on audio_cables)
//   misc:    '{prefix}-MISC-{seq}' — still series-scoped (kept untouched)
const RE_GROUP_MISC = /^([A-Z]{2,3})-MISC-(\d+)$/;
const RE_GROUP_LTD = /^LTD-([A-Z0-9]{4,24})$/;
const RE_GROUP_CATALOG = /^([A-Z]{2,3})$/;

// Variant SKU regexes (Phase 5 shape — variants are still series-specific).
//   catalog: '{prefix}-{length}{pattern}{?-R}' — 'SC-12GL', 'SC-12GL-R'
//   ltd:     '{prefix}-LTD-{slug}' — 'SC-LTD-PHISH26'
//   misc:    '{prefix}-MISC-{seq}' — equals the group SKU, untouched
const RE_VARIANT_CATALOG = /^([A-Z]{2,3})-(\d+)([A-Z]{2,3})(-R)?$/;
const RE_VARIANT_LTD = /^([A-Z]{2,3})-LTD-([A-Z0-9]{4,24})$/;

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
 * names. Group SKUs carry less than variant SKUs do — series and connector
 * details live on audio_cables, not in the group identity.
 *
 * Returns an object with at least `kind`. Shape per kind:
 *   - 'catalog': pattern_code, pattern_name. No prefix (lives on the cable).
 *   - 'misc':    prefix, series, misc_seq. MISC stays series-scoped.
 *   - 'ltd':     slug. No prefix (LTD editions span series).
 *
 * Unknown pattern code yields kind='catalog' with pattern_name=null. Truly
 * malformed inputs return { kind: null }.
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
    const [, slug] = m;
    return { kind: "ltd", slug };
  }

  m = sku.match(RE_GROUP_CATALOG);
  if (m) {
    const [, patternCode] = m;
    const pattern = patternForCode(patternCode);
    return {
      kind: "catalog",
      pattern_code: patternCode,
      pattern_name: pattern ? (pattern.name ?? null) : null,
    };
  }

  return { kind: null };
}

/**
 * Parse a user-facing variant SKU string into structural components.
 *
 * Variant SKUs are series-specific (the customer sees `SC-12GL` or
 * `SC-LTD-PHISH26`); group SKUs are not (post-Phase-5: `GL`, `LTD-PHISH26`).
 * parseVariantSku derives the group SKU from the variant on the way back.
 *
 * Per-kind result shape:
 *   - 'catalog': group_sku ('GL'), prefix, series, length, pattern_code,
 *                pattern_name, connector_code, connector_display
 *   - 'misc':    group_sku (= sku), prefix, series, misc_seq
 *   - 'ltd':     group_sku ('LTD-{slug}'), prefix, series, slug
 *
 * Returns { kind: null } on malformed input.
 */
export function parseVariantSku(sku) {
  if (!sku || typeof sku !== "string") return { kind: null };

  // MISC variant SKU equals group SKU (still '{prefix}-MISC-{seq}').
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

  // LTD variant: '{prefix}-LTD-{slug}'. Group SKU drops the prefix.
  m = sku.match(RE_VARIANT_LTD);
  if (m) {
    const [, prefix, slug] = m;
    return {
      kind: "ltd",
      group_sku: `LTD-${slug}`,
      prefix,
      series: seriesForPrefix(prefix),
      slug,
    };
  }

  // Catalog variant: '{prefix}-{length}{pattern}{?-R}'. Group SKU is
  // pattern_code only.
  m = sku.match(RE_VARIANT_CATALOG);
  if (m) {
    const [, prefix, lengthStr, patternCode, raSuffix] = m;
    const connectorCode = raSuffix ?? "";
    const pattern = patternForCode(patternCode);
    return {
      kind: "catalog",
      group_sku: patternCode,
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
 * Catalog: '{prefix}-{length}{pattern_code}{connector_code}' — needs prefix
 *   from audio_cables since the catalog group SKU doesn't carry it.
 * LTD:     '{prefix}-LTD-{slug}' — same; LTD group SKU is series-agnostic.
 * MISC:    returns group_sku (which still includes the prefix).
 *
 * Returns null if the inputs are invalid.
 */
export function formatVariantSku({ prefix, group_sku, length, connector_code }) {
  const parsed = parseGroupSku(group_sku);
  if (parsed.kind === null) return null;

  if (parsed.kind === "misc") {
    // MISC group SKU carries the prefix and equals the variant SKU.
    return group_sku;
  }

  if (parsed.kind === "ltd") {
    if (!prefix) return null;
    return `${prefix}-LTD-${parsed.slug}`;
  }

  // catalog
  if (!prefix || length == null) return null;
  const cc = connector_code ?? "";
  return `${prefix}-${length}${parsed.pattern_code}${cc}`;
}

/** Return all known series prefixes (sorted). */
export function allPrefixes() {
  return Object.keys(SERIES).sort();
}

/** Return all known patterns (list of dicts). */
export function allPatterns() {
  return Object.values(PATTERNS);
}
