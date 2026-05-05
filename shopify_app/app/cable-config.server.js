/**
 * Cable config resolver — single source of truth for cable attributes.
 *
 * Loads the YAML config under util/product_lines/ at module init and exposes
 * helpers to resolve series, patterns, and SKU structure. Mirrors the Python
 * resolver in greenlight/cable_config.py — both are kept honest by
 * tests/sku_fixtures.json.
 *
 * This module is read-only. It does NOT touch the database. Callers that
 * need DB-backed fields (length for MISC/LTD, descriptions for variants)
 * read those from cable_skus separately and combine with the resolver's
 * output.
 *
 * See docs/CABLE_VARIANTS_REFACTOR.md § Phase 3 for design rationale.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import yaml from "js-yaml";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// This file lives at shopify_app/app/cable-config.server.js;
// YAML is at <repo_root>/util/product_lines/.
const PRODUCT_LINES_DIR = resolve(__dirname, "..", "..", "util", "product_lines");

const SERIES_FILES = [
  "studio_classic.yaml",
  "studio_vocal.yaml",
  "tour_classic.yaml",
  "tour_vocal.yaml",
];

// SKU pattern regexes — order: MISC, LTD, then catalog (matches Python ordering).
const RE_MISC = /^([A-Z]{2,3})-MISC-(\d+)$/;
const RE_LTD = /^([A-Z]{2,3})-LTD-([A-Z0-9]{4,12})$/;
const RE_CATALOG = /^([A-Z]{2,3})-(\d+)([A-Z]{2,3})(-R)?$/;

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

// Cache YAML at module init. Both apps load once at startup.
const PATTERNS = loadPatterns();
const SERIES = loadSeries();

/** Return the full series name for a SKU prefix, or null if unknown. */
export function seriesForPrefix(prefix) {
  const s = SERIES[prefix];
  return s ? (s.product_line ?? null) : null;
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
 * Parse a SKU into its structural components + YAML-resolved names.
 *
 * Returns an object with at least `kind`. For parseable SKUs:
 *   - 'catalog': series_prefix, series, length, pattern_code, pattern_name,
 *                connector_code, connector_display
 *   - 'misc':    series_prefix, series  (length lives on cable_skus.length)
 *   - 'ltd':     series_prefix, series, slug  (length lives on cable_skus.length)
 *
 * Unknown prefix or pattern code yields kind='catalog' with the unknown
 * field's resolved name as null — structural parse stays useful for
 * diagnostics. Truly malformed inputs (no recognized shape) return
 * { kind: null }.
 */
export function parseSku(sku) {
  if (!sku || typeof sku !== "string") return { kind: null };

  // MISC variant: {prefix}-MISC-{seq}
  let m = sku.match(RE_MISC);
  if (m) {
    const prefix = m[1];
    return {
      kind: "misc",
      series_prefix: prefix,
      series: seriesForPrefix(prefix),
    };
  }

  // LTD edition: {prefix}-LTD-{slug}
  m = sku.match(RE_LTD);
  if (m) {
    const [, prefix, slug] = m;
    return {
      kind: "ltd",
      series_prefix: prefix,
      series: seriesForPrefix(prefix),
      slug,
    };
  }

  // Catalog SKU: {prefix}-{length}{pattern}{?-R}
  m = sku.match(RE_CATALOG);
  if (m) {
    const prefix = m[1];
    const length = parseInt(m[2], 10);
    const patternCode = m[3];
    const connectorCode = m[4] ?? "";
    const pattern = patternForCode(patternCode);
    return {
      kind: "catalog",
      series_prefix: prefix,
      series: seriesForPrefix(prefix),
      length,
      pattern_code: patternCode,
      pattern_name: pattern ? (pattern.name ?? null) : null,
      connector_code: connectorCode,
      connector_display: connectorDisplay(prefix, connectorCode),
    };
  }

  return { kind: null };
}

/** Return all known series prefixes (sorted). */
export function allPrefixes() {
  return Object.keys(SERIES).sort();
}

/** Return all known patterns (list of dicts). */
export function allPatterns() {
  return Object.values(PATTERNS);
}
