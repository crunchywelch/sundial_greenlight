/**
 * Smoke test for LTD CRUD against the Phase 4 sku_group schema.
 *
 * Drives editions.server.js end-to-end: createLtdEdition → getEdition →
 * updateEdition (description and active toggle). Verifies the sku_group
 * row has only the minimal columns and that listEditions filters work.
 *
 * Cleans up the test row on success or failure.
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
  listEditions,
  EditionConflictError,
  EditionValidationError,
} from "../app/editions.server.js";
import { parseGroupSku, parseVariantSku, formatVariantSku } from "../app/cable-config.server.js";

const SMOKE_SKU = "SC-LTD-SMOKE2606";
const SMOKE_PREFIX = "SC";
const SMOKE_SLUG = "SMOKE2606";
const SMOKE_DESC = "Phase 4 smoke test — auto-cleanup";

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
  await query(`DELETE FROM sku_group WHERE sku = $1`, [SMOKE_SKU]);
}

async function run() {
  console.log(`\n=== Phase 4 LTD CRUD smoke test against ${process.env.PGDATABASE}@${process.env.PGHOST} ===\n`);

  await cleanup();

  // 1. Resolver
  console.log("Step 1: parseGroupSku / parseVariantSku / formatVariantSku round-trip");
  const groupParsed = parseGroupSku(SMOKE_SKU);
  check("parseGroupSku → kind=ltd", groupParsed.kind === "ltd", JSON.stringify(groupParsed));
  check("parseGroupSku → series=Studio Classic", groupParsed.series === "Studio Classic");
  check("parseGroupSku → slug matches", groupParsed.slug === SMOKE_SLUG);

  const variantParsed = parseVariantSku(SMOKE_SKU);
  check("parseVariantSku of LTD passes through as group", variantParsed.kind === "ltd" && variantParsed.group_sku === SMOKE_SKU);
  const formatted = formatVariantSku({ group_sku: SMOKE_SKU });
  check("formatVariantSku of LTD returns group sku", formatted === SMOKE_SKU);

  const catalogVariant = parseVariantSku("SC-12GL-R");
  check("parseVariantSku catalog → group SC-GL", catalogVariant.kind === "catalog" && catalogVariant.group_sku === "SC-GL");
  check("parseVariantSku catalog → length 12", catalogVariant.length === 12);
  check("parseVariantSku catalog → connector_code -R", catalogVariant.connector_code === "-R");
  const catalogRoundTrip = formatVariantSku(catalogVariant);
  check("catalog round-trip SC-12GL-R", catalogRoundTrip === "SC-12GL-R");

  // 2. createLtdEdition writes minimal row
  console.log("\nStep 2: createLtdEdition");
  const created = await createLtdEdition({
    seriesPrefix: SMOKE_PREFIX,
    slug: SMOKE_SLUG,
    description: SMOKE_DESC,
  });
  check(`createLtdEdition returned sku=${SMOKE_SKU}`, created.sku === SMOKE_SKU, `got ${created.sku}`);
  check("createLtdEdition returned series=Studio Classic", created.series === "Studio Classic");

  // 3. sku_group row shape
  console.log("\nStep 3: sku_group row shape");
  const sgRow = await query(`SELECT * FROM sku_group WHERE sku = $1`, [SMOKE_SKU]);
  check("sku_group row exists", sgRow.rows.length === 1);
  if (sgRow.rows.length === 1) {
    const r = sgRow.rows[0];
    const cols = Object.keys(r).sort();
    const expected = ["archived_at", "description", "sku"];
    check(`sku_group columns = ${expected.join(",")}`,
      JSON.stringify(cols) === JSON.stringify(expected),
      `got ${cols.join(",")}`);
    check("description preserved", r.description === SMOKE_DESC);
    check("archived_at NULL on create", r.archived_at === null);
  }

  // 4. createLtdEdition is idempotent on conflict
  console.log("\nStep 4: duplicate slug rejected");
  let conflictThrown = false;
  try {
    await createLtdEdition({ seriesPrefix: SMOKE_PREFIX, slug: SMOKE_SLUG, description: "duplicate" });
  } catch (e) {
    conflictThrown = e instanceof EditionConflictError;
  }
  check("duplicate insert throws EditionConflictError", conflictThrown);

  // 5. Required-field validation
  console.log("\nStep 5: validation rejects missing fields");
  let validationThrown = false;
  try {
    await createLtdEdition({ seriesPrefix: SMOKE_PREFIX, slug: "BADSLUG", description: "" });
  } catch (e) {
    validationThrown = e instanceof EditionValidationError && e.field === "description";
  }
  check("missing description throws EditionValidationError", validationThrown);

  // 6. getEdition derives display fields
  console.log("\nStep 6: getEdition shape");
  const ed = await getEdition(SMOKE_SKU);
  check("getEdition returned non-null", ed !== null);
  if (ed) {
    check("series=Studio Classic (derived)", ed.series === "Studio Classic");
    check("prefix=SC", ed.prefix === "SC");
    check(`slug=${SMOKE_SLUG}`, ed.slug === SMOKE_SLUG);
    check(`description=${SMOKE_DESC}`, ed.description === SMOKE_DESC);
    check("active=true", ed.active === true);
    check("archived_at=null", ed.archived_at === null);
    check("cable_count=0", ed.cable_count === 0);
  }

  // 7. listEditions filters
  console.log("\nStep 7: listEditions filters");
  const activeList = await listEditions("active");
  const inActive = activeList.find((e) => e.sku === SMOKE_SKU);
  check("smoke edition appears in active list", !!inActive);

  // 8. Archive
  console.log("\nStep 8: updateEdition archive");
  await updateEdition(SMOKE_SKU, { active: false });
  const archived = await getEdition(SMOKE_SKU);
  check("active=false after archive", archived.active === false);
  check("archived_at populated", archived.archived_at !== null);
  const archivedList = await listEditions("archived");
  check("smoke edition appears in archived list", !!archivedList.find((e) => e.sku === SMOKE_SKU));
  const stillActiveList = await listEditions("active");
  check("smoke edition NOT in active list after archive", !stillActiveList.find((e) => e.sku === SMOKE_SKU));

  // 9. Unarchive
  console.log("\nStep 9: updateEdition unarchive");
  await updateEdition(SMOKE_SKU, { active: true });
  const reactivated = await getEdition(SMOKE_SKU);
  check("active=true after unarchive", reactivated.active === true);
  check("archived_at cleared", reactivated.archived_at === null);

  // 10. Description edit (allowed since cable_count=0)
  console.log("\nStep 10: updateEdition description (unlocked)");
  await updateEdition(SMOKE_SKU, { description: "edited" });
  const edited = await getEdition(SMOKE_SKU);
  check("description updated", edited.description === "edited");
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
