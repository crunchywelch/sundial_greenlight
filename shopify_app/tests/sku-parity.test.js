/**
 * Parity test for the JS SKU resolver (Phase 4).
 *
 * Loads tests/sku_fixtures.json (and tests/sku_fixtures_prod.json if present)
 * and dispatches each entry on its `type` discriminator:
 *
 *   - "group":      asserts parseGroupSku(sku) deepEquals expected
 *   - "variant":    asserts parseVariantSku(sku) deepEquals expected
 *   - "round_trip": asserts formatVariantSku(parseVariantSku(sku)) === sku
 *
 * The same fixtures are consumed by the Python parity test
 * (tests/test_sku_parity.py) — same input, same output, enforced both sides.
 *
 * Run: npm test  (or node --test shopify_app/tests/sku-parity.test.js)
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  parseGroupSku,
  parseVariantSku,
  formatVariantSku,
} from "../app/cable-config.server.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const FIXTURES_DIR = resolve(__dirname, "..", "..", "tests");
const FIXTURE_FILES = ["sku_fixtures.json", "sku_fixtures_prod.json"];

const fixtures = [];
for (const fname of FIXTURE_FILES) {
  const path = resolve(FIXTURES_DIR, fname);
  if (!existsSync(path)) continue;
  fixtures.push(...JSON.parse(readFileSync(path, "utf8")));
}

for (const entry of fixtures) {
  const label = entry.name ?? entry.sku;

  if (entry.type === "group") {
    test(label, () => {
      const actual = parseGroupSku(entry.sku);
      assert.deepStrictEqual(actual, entry.expected,
        `parseGroupSku(${JSON.stringify(entry.sku)}) mismatch`);
    });
  } else if (entry.type === "variant") {
    test(label, () => {
      const actual = parseVariantSku(entry.sku);
      assert.deepStrictEqual(actual, entry.expected,
        `parseVariantSku(${JSON.stringify(entry.sku)}) mismatch`);
    });
  } else if (entry.type === "round_trip") {
    test(label, () => {
      const parsed = parseVariantSku(entry.sku);
      assert.notStrictEqual(parsed.kind, null,
        `parseVariantSku(${JSON.stringify(entry.sku)}) returned kind=null`);
      const formatted = formatVariantSku(parsed);
      assert.strictEqual(formatted, entry.sku,
        `round-trip mismatch: parsed=${JSON.stringify(parsed)} formatted=${JSON.stringify(formatted)}`);
    });
  } else {
    test(`UNKNOWN TYPE: ${label}`, () => {
      assert.fail(`Fixture has no type discriminator or unknown type: ${entry.type}`);
    });
  }
}
