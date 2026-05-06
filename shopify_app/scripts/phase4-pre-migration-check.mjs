/**
 * Pre-migration parity check for Phase 4.
 *
 * Reads every cable_skus.sku and audio_cables.sku from the database and
 * verifies that the new resolver can:
 *   - parse every cable_skus.sku via parseGroupSku (currently the SKUs are
 *     variant-shaped for catalog rows, so this WILL fail for catalog —
 *     that's expected and reported, not a blocker; the migration repoints
 *     these in step 5)
 *   - parse every audio_cables.sku via parseVariantSku
 *   - round-trip each audio_cables.sku via formatVariantSku
 *
 * Also reports the planned migration outputs:
 *   - the set of distinct (prefix, pattern_code) catalog group SKUs that
 *     need to be inserted in step 4
 *   - the set of audio_cables that don't backfill cleanly (any cable whose
 *     sku doesn't parse as a variant)
 *
 * Exit 0 if migration is safe, non-zero otherwise.
 *
 * Run: set -a; source .env; set +a; node scripts/phase4-pre-migration-check.mjs
 */
import { query } from "../app/db.server.js";
import {
  parseVariantSku,
  formatVariantSku,
  parseGroupSku,
} from "../app/cable-config.server.js";

let safeToMigrate = true;
const issues = [];

function fail(category, detail) {
  safeToMigrate = false;
  issues.push({ category, detail });
}

async function checkAudioCables() {
  const result = await query(`SELECT serial_number, sku FROM audio_cables ORDER BY serial_number`);
  const rows = result.rows;
  console.log(`\n[1] audio_cables: ${rows.length} rows`);

  let okCount = 0;
  let parseFails = 0;
  let roundTripFails = 0;
  const catalogGroups = new Set();

  for (const row of rows) {
    const parsed = parseVariantSku(row.sku);
    if (parsed.kind === null) {
      parseFails++;
      fail("audio_cables.parse", `${row.serial_number}: sku=${JSON.stringify(row.sku)} did not parse as variant`);
      continue;
    }
    const formatted = formatVariantSku(parsed);
    if (formatted !== row.sku) {
      roundTripFails++;
      fail("audio_cables.round_trip", `${row.serial_number}: sku=${JSON.stringify(row.sku)} → parsed=${JSON.stringify(parsed)} → formatted=${JSON.stringify(formatted)}`);
      continue;
    }
    if (parsed.kind === "catalog") catalogGroups.add(parsed.group_sku);
    okCount++;
  }
  console.log(`    ✓ parsed + round-tripped: ${okCount}`);
  if (parseFails) console.log(`    ✗ parse failures:    ${parseFails}`);
  if (roundTripFails) console.log(`    ✗ round-trip fails:  ${roundTripFails}`);
  console.log(`    distinct catalog groups derived: ${catalogGroups.size}`);
  return catalogGroups;
}

async function checkCableSkus() {
  const result = await query(`SELECT sku FROM cable_skus ORDER BY sku`);
  const rows = result.rows;
  console.log(`\n[2] cable_skus: ${rows.length} rows`);

  // Today cable_skus.sku is variant-shaped for catalog (e.g. SC-12GL) and
  // group-shaped for MISC/LTD (e.g. SC-MISC-42). After migration step 5 the
  // catalog rows are deleted and replaced with group rows. We just want to
  // confirm our resolver understands the variant-shaped rows so the
  // migration's REGEXP_REPLACE produces the right group SKU.
  let catalogVariants = 0;
  let miscOrLtd = 0;
  let unrecognized = 0;
  const catalogGroupsFromCableSkus = new Set();

  for (const row of rows) {
    const variant = parseVariantSku(row.sku);
    if (variant.kind === "catalog") {
      catalogVariants++;
      catalogGroupsFromCableSkus.add(variant.group_sku);
    } else if (variant.kind === "misc" || variant.kind === "ltd") {
      miscOrLtd++;
    } else {
      // Could be a group-shaped sku already (SC-GL) — try parseGroupSku
      const group = parseGroupSku(row.sku);
      if (group.kind === "catalog") {
        catalogGroupsFromCableSkus.add(row.sku);
        // Note: this is unusual today; flag for review
        console.log(`    note: cable_skus already has group-shaped row: ${row.sku}`);
      } else {
        unrecognized++;
        fail("cable_skus.unrecognized", `sku=${JSON.stringify(row.sku)}`);
      }
    }
  }
  console.log(`    catalog variants: ${catalogVariants}`);
  console.log(`    misc/ltd:         ${miscOrLtd}`);
  if (unrecognized) console.log(`    ✗ unrecognized:   ${unrecognized}`);
  console.log(`    distinct catalog groups derived: ${catalogGroupsFromCableSkus.size}`);
  return catalogGroupsFromCableSkus;
}

function compareGroups(fromCables, fromCableSkus) {
  console.log(`\n[3] catalog group reconciliation`);
  const onlyInCables = [...fromCables].filter((g) => !fromCableSkus.has(g));
  const onlyInCableSkus = [...fromCableSkus].filter((g) => !fromCables.has(g));
  if (onlyInCables.length === 0 && onlyInCableSkus.length === 0) {
    console.log(`    ✓ same set in both tables (${fromCables.size} groups)`);
  } else {
    if (onlyInCables.length > 0) {
      console.log(`    note: groups appearing in audio_cables but not derivable from cable_skus:`);
      for (const g of onlyInCables) console.log(`      - ${g}`);
    }
    if (onlyInCableSkus.length > 0) {
      console.log(`    note: groups derivable from cable_skus but not in audio_cables (no cables registered yet):`);
      for (const g of onlyInCableSkus) console.log(`      - ${g}`);
    }
  }
  const allGroups = new Set([...fromCables, ...fromCableSkus]);
  console.log(`\n    Migration step 4 will INSERT ${allGroups.size} sku_group rows for catalog.`);
  return allGroups;
}

async function checkLengthBackfill() {
  console.log(`\n[4] length backfill simulation`);
  // For variant-shaped audio_cables.sku, the length comes from the SKU itself.
  // For MISC/LTD-shaped audio_cables.sku, the length comes from cable_skus.length
  // (added in Phase 3.5). Verify every audio_cable can resolve a length.
  const result = await query(
    `SELECT ac.serial_number, ac.sku, cs.length AS variant_length
     FROM audio_cables ac
     LEFT JOIN cable_skus cs ON cs.sku = ac.sku`
  );
  let cantResolveLength = 0;
  for (const row of result.rows) {
    const parsed = parseVariantSku(row.sku);
    let length;
    if (parsed.kind === "catalog") {
      length = parsed.length;
    } else if (parsed.kind === "misc" || parsed.kind === "ltd") {
      length = row.variant_length != null ? Number(row.variant_length) : null;
    }
    if (length == null || !Number.isFinite(length) || length <= 0) {
      cantResolveLength++;
      fail("length_backfill", `${row.serial_number}: sku=${row.sku} length=${length}`);
    }
  }
  console.log(`    ✓ ${result.rows.length - cantResolveLength}/${result.rows.length} cables resolve to a positive length`);
  if (cantResolveLength > 0) console.log(`    ✗ ${cantResolveLength} cables fail length backfill`);
}

async function main() {
  console.log(`=== Phase 4 pre-migration parity check against ${process.env.PGDATABASE}@${process.env.PGHOST} ===`);

  const fromCables = await checkAudioCables();
  const fromCableSkus = await checkCableSkus();
  compareGroups(fromCables, fromCableSkus);
  await checkLengthBackfill();

  console.log("\n");
  if (safeToMigrate) {
    console.log("✅ All checks passed — safe to migrate.");
    process.exit(0);
  } else {
    console.log(`❌ ${issues.length} issue(s) — DO NOT run migration:`);
    const byCategory = {};
    for (const i of issues) {
      byCategory[i.category] = (byCategory[i.category] || 0) + 1;
    }
    for (const [cat, n] of Object.entries(byCategory)) {
      console.log(`  ${cat}: ${n}`);
    }
    console.log("\nFirst 10 issues:");
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
