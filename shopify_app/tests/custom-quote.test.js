/**
 * Unit tests for the Custom Cable Sets pricing model
 * (app/custom-config.server.js). Pure functions — no DB, always run.
 *
 * Run: cd shopify_app && npm test
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  PRICING,
  PATTERNS,
  FABRICS,
  COLORS,
  colorLabel,
  configCatalog,
  unitPrice,
  quoteCustomSet,
} from "../app/custom-config.server.js";

test("unitPrice = length * $5/ft + $10/cable", () => {
  assert.equal(unitPrice(20), 110); // 20*5 + 10
  assert.equal(unitPrice(1), 15);
  assert.equal(unitPrice(0.5), 12.5);
});

test("matches the worked example from the page copy", () => {
  // 100 ft of XLR cut into five 20-ft mic cables → $550.
  const q = quoteCustomSet([{ lengthFt: 20, quantity: 5 }]);
  assert.equal(q.totalFeet, 100);
  assert.equal(q.totalCables, 5);
  assert.equal(q.cableCost, 500); // 100ft * $5
  assert.equal(q.connectorCost, 50); // 5 * $10
  assert.equal(q.total, 550);
  assert.equal(q.meetsMinimum, true);
});

test("total equals sum of line totals and cable+connector split", () => {
  const q = quoteCustomSet([
    { lengthFt: 10, quantity: 4 },
    { lengthFt: 25, quantity: 2 },
  ]);
  assert.equal(q.totalFeet, 10 * 4 + 25 * 2); // 90
  assert.equal(q.totalCables, 6);
  assert.equal(q.total, q.cableCost + q.connectorCost);
  const lineSum = q.lines.reduce((s, l) => s + l.lineTotal, 0);
  assert.equal(q.total, lineSum);
});

test("flags runs under the 100 ft minimum", () => {
  const q = quoteCustomSet([{ lengthFt: 10, quantity: 4 }]); // 40 ft
  assert.equal(q.meetsMinimum, false);
  assert.equal(q.minTotalFeet, PRICING.minTotalFeet);
});

test("minimum is on TOTAL feet, not per cable", () => {
  // Twenty 5-ft cables = 100 ft total → meets minimum even though each is short.
  const q = quoteCustomSet([{ lengthFt: 5, quantity: 20 }]);
  assert.equal(q.totalFeet, 100);
  assert.equal(q.meetsMinimum, true);
});

test("pattern values are unique and color counts are sane", () => {
  // A duplicate `value` makes the page's find()-by-value resolve to the wrong
  // pattern (and silently drop the dupe in the <select>). Guard against it.
  const values = PATTERNS.map((p) => p.value);
  assert.equal(new Set(values).size, values.length, `duplicate pattern value in [${values}]`);
  for (const p of PATTERNS) {
    assert.ok(p.colors >= 1 && p.colors <= 3, `pattern '${p.value}' has out-of-range colors=${p.colors}`);
  }
});

test("colors are keyed per fabric and every fabric has a color list", () => {
  for (const f of FABRICS) {
    assert.ok(Array.isArray(COLORS[f.value]), `missing colors for fabric '${f.value}'`);
    assert.ok(COLORS[f.value].length > 0, `empty color list for fabric '${f.value}'`);
  }
  // Embedded catalog hands the page the same per-fabric shape.
  const cat = configCatalog();
  assert.deepEqual(Object.keys(cat.colors).sort(), FABRICS.map((f) => f.value).sort());
});

test("colorLabel resolves across fabrics and falls back gracefully", () => {
  assert.equal(colorLabel("walnut-brown"), "Walnut Brown"); // rayon
  assert.equal(colorLabel("burnt-orange"), "Burnt Orange"); // cotton
  assert.equal(colorLabel("black"), "Black"); // present in both
  assert.equal(colorLabel("nonexistent-color"), "nonexistent-color");
});

test("rejects malformed lines", () => {
  assert.throws(() => quoteCustomSet([]), RangeError);
  assert.throws(() => quoteCustomSet([{ lengthFt: 0, quantity: 1 }]), RangeError);
  assert.throws(() => quoteCustomSet([{ lengthFt: 10, quantity: 0 }]), RangeError);
  assert.throws(() => quoteCustomSet([{ lengthFt: 10, quantity: 1.5 }]), RangeError);
  assert.throws(() => quoteCustomSet([{ lengthFt: -5, quantity: 2 }]), RangeError);
});
