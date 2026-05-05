/**
 * Smoke test for LTD CRUD against the migrated schema.
 *
 * Drives editions.server.js end-to-end (createLtdEdition, getEdition,
 * updateEdition archive/unarchive) and verifies the rows look right at
 * each step. Skips the Shopify product-create call (needs admin GraphQL
 * auth) — verify that piece in the browser.
 *
 * Cleans up the test rows on success or failure (cascade FK from
 * cable_ltd_metadata to cable_skus).
 *
 * Usage:
 *   set -a; source .env; set +a
 *   node scripts/smoke-test-ltd.mjs
 */
import { query } from "../app/db.server.js";
import {
  createLtdEdition,
  getEdition,
  updateEdition,
  EditionConflictError,
} from "../app/editions.server.js";
import { parseSku } from "../app/cable-config.server.js";

const SMOKE_SKU = "SC-LTD-SMOKE2605";
const SMOKE_PREFIX = "SC";
const SMOKE_SLUG = "SMOKE2605";

let ok = true;
const failures = [];

function check(label, cond, detail) {
  if (cond) {
    console.log(`  ✅ ${label}`);
  } else {
    console.log(`  ❌ ${label}`);
    if (detail) console.log(`      ${detail}`);
    ok = false;
    failures.push(label);
  }
}

async function cleanup() {
  // CASCADE on FK from cable_ltd_metadata to cable_skus, so deleting
  // cable_skus is enough — but be defensive.
  await query(`DELETE FROM cable_ltd_metadata WHERE sku = $1`, [SMOKE_SKU]);
  await query(`DELETE FROM cable_skus WHERE sku = $1`, [SMOKE_SKU]);
}

async function run() {
  console.log(`\n=== LTD CRUD smoke test against ${process.env.PGDATABASE}@${process.env.PGHOST} ===\n`);

  // Pre-clean in case a prior run aborted mid-way
  await cleanup();

  // 1. parseSku derives the right kind/series for the chosen SKU
  console.log("Step 1: parseSku");
  const parsed = parseSku(SMOKE_SKU);
  check(`parseSku → kind=ltd`, parsed.kind === "ltd", `got ${JSON.stringify(parsed)}`);
  check(`parseSku → series_prefix=SC`, parsed.series_prefix === "SC");
  check(`parseSku → series=Studio Classic`, parsed.series === "Studio Classic");
  check(`parseSku → slug=${SMOKE_SLUG}`, parsed.slug === SMOKE_SLUG);

  // 2. createLtdEdition writes the minimal row + sidecar
  console.log("\nStep 2: createLtdEdition");
  const created = await createLtdEdition({
    seriesPrefix: SMOKE_PREFIX,
    slug: SMOKE_SLUG,
    lengthFt: "12",
    description: "Smoke-test edition (auto-cleanup)",
    eventName: "Smoke Test 2026",
    createdBy: "AUTO",
    notes: "Created and deleted by scripts/smoke-test-ltd.mjs",
  });
  check(`createLtdEdition returned sku=${SMOKE_SKU}`, created.sku === SMOKE_SKU, `got ${created.sku}`);
  check(`createLtdEdition returned series=Studio Classic`, created.series === "Studio Classic");

  // 3. cable_skus row has only the minimal columns populated
  console.log("\nStep 3: cable_skus row shape");
  const csRow = await query(`SELECT * FROM cable_skus WHERE sku = $1`, [SMOKE_SKU]);
  check(`cable_skus row exists`, csRow.rows.length === 1);
  if (csRow.rows.length === 1) {
    const r = csRow.rows[0];
    const cols = Object.keys(r).sort();
    const expectedCols = ["created_at", "description", "length", "sku", "updated_at"];
    check(`cable_skus columns = ${expectedCols.join(",")}`,
      JSON.stringify(cols) === JSON.stringify(expectedCols),
      `got ${cols.join(",")}`);
    check(`length stored as 12 (numeric)`, Number(r.length) === 12, `got ${r.length}`);
    check(`description preserved`, r.description === "Smoke-test edition (auto-cleanup)");
  }

  // 4. cable_ltd_metadata row exists with expected fields, no `active` column
  console.log("\nStep 4: cable_ltd_metadata row shape");
  const lmRow = await query(`SELECT * FROM cable_ltd_metadata WHERE sku = $1`, [SMOKE_SKU]);
  check(`cable_ltd_metadata row exists`, lmRow.rows.length === 1);
  if (lmRow.rows.length === 1) {
    const r = lmRow.rows[0];
    const cols = Object.keys(r).sort();
    const expectedCols = ["archived_at", "created_at", "created_by", "event_name", "notes", "sku"];
    check(`cable_ltd_metadata columns = ${expectedCols.join(",")}`,
      JSON.stringify(cols) === JSON.stringify(expectedCols),
      `got ${cols.join(",")}`);
    check(`event_name preserved`, r.event_name === "Smoke Test 2026");
    check(`created_by preserved`, r.created_by === "AUTO");
    check(`archived_at NULL on create`, r.archived_at === null);
  }

  // 5. createLtdEdition is idempotent on conflict
  console.log("\nStep 5: duplicate slug rejected");
  let conflictThrown = false;
  try {
    await createLtdEdition({
      seriesPrefix: SMOKE_PREFIX,
      slug: SMOKE_SLUG,
      lengthFt: "10",
      description: "duplicate",
      eventName: "Should fail",
    });
  } catch (e) {
    conflictThrown = e instanceof EditionConflictError;
  }
  check(`duplicate insert throws EditionConflictError`, conflictThrown);

  // 6. getEdition returns the same shape consumers expect (with derived `active`)
  console.log("\nStep 6: getEdition derives display fields");
  const ed = await getEdition(SMOKE_SKU);
  check(`getEdition returned non-null`, ed !== null);
  if (ed) {
    check(`series=Studio Classic (derived)`, ed.series === "Studio Classic");
    check(`color_pattern='Limited Edition' (sentinel)`, ed.color_pattern === "Limited Edition");
    check(`core_cable=Canare GS-6 (from YAML)`, ed.core_cable === "Canare GS-6");
    check(`braid_material=Rayon (from YAML)`, ed.braid_material === "Rayon");
    check(`connector_type=TS–TS (from YAML, em-dash)`, ed.connector_type === "TS–TS",
      `got ${JSON.stringify(ed.connector_type)}`);
    check(`length=12 (numeric)`, Number(ed.length) === 12);
    check(`active=true (derived from archived_at IS NULL)`, ed.active === true);
    check(`cable_count=0`, ed.cable_count === 0);
    check(`event_name=Smoke Test 2026`, ed.event_name === "Smoke Test 2026");
    check(`slug=${SMOKE_SLUG}`, ed.slug === SMOKE_SLUG);
  }

  // 7. updateEdition archive sets archived_at
  console.log("\nStep 7: updateEdition archive");
  await updateEdition(SMOKE_SKU, { active: false });
  const archived = await getEdition(SMOKE_SKU);
  check(`active=false after archive`, archived.active === false);
  check(`archived_at populated`, archived.archived_at !== null);

  // 8. updateEdition unarchive clears archived_at
  console.log("\nStep 8: updateEdition unarchive");
  await updateEdition(SMOKE_SKU, { active: true });
  const reactivated = await getEdition(SMOKE_SKU);
  check(`active=true after unarchive`, reactivated.active === true);
  check(`archived_at cleared`, reactivated.archived_at === null);

  // 9. updateEdition event_name + notes
  console.log("\nStep 9: updateEdition event_name + notes");
  await updateEdition(SMOKE_SKU, { eventName: "Smoke Test 2026 (renamed)", notes: "updated" });
  const renamed = await getEdition(SMOKE_SKU);
  check(`event_name updated`, renamed.event_name === "Smoke Test 2026 (renamed)");
  check(`notes updated`, renamed.notes === "updated");

  // 10. updateEdition length+description (allowed since cable_count=0)
  console.log("\nStep 10: updateEdition length + description (unlocked, no cables)");
  await updateEdition(SMOKE_SKU, { lengthFt: "15", description: "edited" });
  const edited = await getEdition(SMOKE_SKU);
  check(`length updated to 15`, Number(edited.length) === 15);
  check(`description updated`, edited.description === "edited");
}

async function main() {
  try {
    await run();
  } catch (e) {
    console.error("\n❌ Unexpected error:", e);
    failures.push(`unexpected: ${e.message}`);
    ok = false;
  } finally {
    console.log("\nCleaning up smoke-test rows...");
    try {
      await cleanup();
      console.log("  ✅ cleanup complete");
    } catch (e) {
      console.error("  ❌ cleanup failed:", e.message);
      ok = false;
    }
  }

  console.log();
  if (ok) {
    console.log("✅ All smoke-test checks passed.");
    process.exit(0);
  } else {
    console.log(`❌ ${failures.length} check(s) failed:\n  - ${failures.join("\n  - ")}`);
    process.exit(1);
  }
}

main();
