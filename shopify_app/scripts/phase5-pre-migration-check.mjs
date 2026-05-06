/**
 * Pre-migration parity check for Phase 5.
 *
 * Verifies the prefix-collapse migration is safe to run:
 *   - every catalog and LTD sku_group has a parseable {prefix}-{rest} shape
 *   - the post-collapse group identifiers don't have description conflicts
 *     (when multiple per-series groups collapse to the same shape, their
 *     descriptions should agree or the migration needs to pick one)
 *   - every audio_cables row's prefix is recoverable from its current sku_group
 *
 * MISC groups (`{prefix}-MISC-{seq}`) are untouched; they're recognized and
 * skipped in the collapse logic.
 *
 * Exit 0 if migration is safe, non-zero otherwise.
 *
 * Run: cd shopify_app && set -a; source .env; set +a
 *      node scripts/phase5-pre-migration-check.mjs
 */
import { query } from "../app/db.server.js";

let safeToMigrate = true;
const issues = [];

function fail(category, detail) {
  safeToMigrate = false;
  issues.push({ category, detail });
}

const RE_CATALOG = /^([A-Z]{2,3})-([A-Z]{2,3})$/;
const RE_LTD = /^([A-Z]{2,3})-LTD-([A-Z0-9]{4,12})$/;
const RE_MISC = /^([A-Z]{2,3})-MISC-(\d+)$/;

function classify(sku) {
  let m = sku.match(RE_MISC);
  if (m) return { kind: "misc", prefix: m[1], rest: `MISC-${m[2]}`, newSku: sku };
  m = sku.match(RE_LTD);
  if (m) return { kind: "ltd", prefix: m[1], rest: `LTD-${m[2]}`, newSku: `LTD-${m[2]}` };
  m = sku.match(RE_CATALOG);
  if (m) return { kind: "catalog", prefix: m[1], rest: m[2], newSku: m[2] };
  return null;
}

async function checkSkuGroups() {
  const result = await query(`SELECT sku, description, archived_at FROM sku_group ORDER BY sku`);
  const rows = result.rows;
  console.log(`\n[1] sku_group: ${rows.length} rows`);

  const collapseMap = {}; // newSku -> [ {oldSku, description, archived_at} ]
  let unparseable = 0;
  let miscCount = 0;
  let catalogCount = 0;
  let ltdCount = 0;

  for (const row of rows) {
    const c = classify(row.sku);
    if (!c) {
      unparseable++;
      fail("sku_group.unparseable", `sku=${JSON.stringify(row.sku)} doesn't match catalog/MISC/LTD shape`);
      continue;
    }
    if (c.kind === "misc") {
      miscCount++;
      continue; // unchanged
    }
    if (c.kind === "catalog") catalogCount++;
    if (c.kind === "ltd") ltdCount++;
    const bucket = collapseMap[c.newSku] || [];
    bucket.push({ oldSku: row.sku, description: row.description, archived_at: row.archived_at, kind: c.kind });
    collapseMap[c.newSku] = bucket;
  }

  console.log(`    catalog: ${catalogCount}, ltd: ${ltdCount}, misc (unchanged): ${miscCount}`);
  if (unparseable) console.log(`    ✗ unparseable: ${unparseable}`);
  console.log(`    distinct collapsed groups: ${Object.keys(collapseMap).length}`);

  // Report description conflicts on collapse
  let conflicts = 0;
  for (const [newSku, bucket] of Object.entries(collapseMap)) {
    if (bucket.length === 1) continue;
    const descs = new Set(bucket.map((b) => b.description));
    if (descs.size > 1) {
      conflicts++;
      console.log(`    ⚠️  description conflict on ${newSku}:`);
      for (const b of bucket) {
        console.log(`        ${b.oldSku} → ${JSON.stringify(b.description)}`);
      }
    }
  }
  if (conflicts > 0) {
    console.log(`    ${conflicts} group(s) need a description picked at migration time`);
  } else {
    console.log(`    ✓ no description conflicts on collapse`);
  }

  return collapseMap;
}

async function checkAudioCables() {
  const result = await query(
    `SELECT serial_number, sku_group FROM audio_cables ORDER BY serial_number`
  );
  console.log(`\n[2] audio_cables: ${result.rows.length} rows`);

  let unparseable = 0;
  let prefixFails = 0;
  for (const row of result.rows) {
    const c = classify(row.sku_group);
    if (!c) {
      unparseable++;
      fail("audio_cables.unparseable", `${row.serial_number}: sku_group=${JSON.stringify(row.sku_group)} doesn't classify`);
      continue;
    }
    if (!c.prefix || !/^[A-Z]{2,3}$/.test(c.prefix)) {
      prefixFails++;
      fail("audio_cables.bad_prefix", `${row.serial_number}: prefix from ${row.sku_group} is ${JSON.stringify(c.prefix)}`);
    }
  }
  console.log(`    ✓ ${result.rows.length - unparseable - prefixFails}/${result.rows.length} cables resolve to a valid prefix`);
  if (unparseable) console.log(`    ✗ unparseable sku_group: ${unparseable}`);
  if (prefixFails) console.log(`    ✗ unparseable prefix: ${prefixFails}`);
}

async function main() {
  console.log(`=== Phase 5 pre-migration parity check against ${process.env.PGDATABASE}@${process.env.PGHOST} ===`);
  await checkSkuGroups();
  await checkAudioCables();

  console.log("");
  if (safeToMigrate) {
    console.log("✅ All checks passed — safe to migrate.");
    process.exit(0);
  } else {
    console.log(`❌ ${issues.length} issue(s) — DO NOT run migration:`);
    for (const i of issues.slice(0, 10)) {
      console.log(`  - [${i.category}] ${i.detail}`);
    }
    process.exit(1);
  }
}

main().catch((e) => {
  console.error("unexpected error:", e);
  process.exit(2);
});
