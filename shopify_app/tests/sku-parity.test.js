/**
 * Parity test for the JS SKU resolver.
 *
 * Loads tests/sku_fixtures.json (at repo root) and asserts that
 * shopify_app/app/cable-config.server.js's parseSku returns the expected
 * dict for every fixture entry. The same fixture file is consumed by the
 * Python resolver's parity test (tests/test_sku_parity.py). Same input,
 * same output, enforced on both sides.
 *
 * Run: node --test shopify_app/tests/sku-parity.test.js
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { parseSku } from "../app/cable-config.server.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const FIXTURE_PATH = resolve(__dirname, "..", "..", "tests", "sku_fixtures.json");

const fixtures = JSON.parse(readFileSync(FIXTURE_PATH, "utf8"));

for (const entry of fixtures) {
  const label = entry.name ?? entry.sku;
  test(label, () => {
    const actual = parseSku(entry.sku);
    assert.deepStrictEqual(
      actual,
      entry.expected,
      `parseSku(${JSON.stringify(entry.sku)}) mismatch`
    );
  });
}
