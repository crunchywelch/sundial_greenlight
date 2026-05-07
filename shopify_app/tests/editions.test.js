/**
 * Unit-shaped tests for editions.server.js — validation paths, conflict
 * handling, archive toggle, and listEditions filter behavior.
 *
 * Distinct from scripts/smoke-test-ltd.mjs which is an end-to-end
 * regression check. These tests are smaller, hit the DB sparingly, and
 * isolate each scenario with a unique test slug.
 *
 * Run: cd shopify_app && set -a; source .env; set +a; npm test
 *
 * Tests skip cleanly if PGHOST isn't set (no DB credentials available).
 */

import { test, before, after } from "node:test";
import assert from "node:assert/strict";

// Skip the whole file if the DB env isn't set up — prevents the test
// from failing on a fresh checkout where someone's running `npm test`
// without sourcing .env.
const HAS_DB = Boolean(process.env.PGHOST && process.env.PGDATABASE);

if (!HAS_DB) {
  test("editions.server.js (skipped — no DB env)", { skip: true }, () => {});
} else {
  const { query } = await import("../app/db.server.js");
  const {
    createLtdEdition,
    getEdition,
    updateEdition,
    listEditions,
    EditionValidationError,
    EditionConflictError,
  } = await import("../app/editions.server.js");

  // Unique test prefix per process so parallel test runs don't collide.
  const RUN_TAG = `T${Date.now().toString(36).slice(-6).toUpperCase()}`;
  const slug = (suffix) => `${RUN_TAG}${suffix}`.slice(0, 24);
  const sku = (suffix) => `LTD-${slug(suffix)}`;

  async function deleteIfExists(s) {
    await query(`DELETE FROM sku_group WHERE sku = $1`, [s]);
  }

  // ───────────────────────────────────────────────────────────────────
  // createLtdEdition — input validation (no DB write reached)
  // ───────────────────────────────────────────────────────────────────

  test("createLtdEdition rejects too-short slug", async () => {
    await assert.rejects(
      () => createLtdEdition({ slug: "AB", description: "x" }),
      (e) => e instanceof EditionValidationError && e.field === "slug"
    );
  });

  test("createLtdEdition rejects too-long slug", async () => {
    await assert.rejects(
      () => createLtdEdition({ slug: "A".repeat(25), description: "x" }),
      (e) => e instanceof EditionValidationError && e.field === "slug"
    );
  });

  test("createLtdEdition rejects lowercase slug", async () => {
    await assert.rejects(
      () => createLtdEdition({ slug: "phish26", description: "x" }),
      (e) => e instanceof EditionValidationError && e.field === "slug"
    );
  });

  test("createLtdEdition rejects slug with special chars", async () => {
    await assert.rejects(
      () => createLtdEdition({ slug: "PHISH-26", description: "x" }),
      (e) => e instanceof EditionValidationError && e.field === "slug"
    );
  });

  test("createLtdEdition rejects empty description", async () => {
    await assert.rejects(
      () => createLtdEdition({ slug: slug("VALID"), description: "" }),
      (e) => e instanceof EditionValidationError && e.field === "description"
    );
  });

  test("createLtdEdition rejects whitespace-only description", async () => {
    await assert.rejects(
      () => createLtdEdition({ slug: slug("VALIDB"), description: "   " }),
      (e) => e instanceof EditionValidationError && e.field === "description"
    );
  });

  // ───────────────────────────────────────────────────────────────────
  // createLtdEdition — happy path + conflict (DB-backed)
  // ───────────────────────────────────────────────────────────────────

  test("createLtdEdition writes minimal sku_group row", async (t) => {
    const s = slug("HAPPY");
    t.after(() => deleteIfExists(`LTD-${s}`));

    const result = await createLtdEdition({ slug: s, description: "happy path" });
    assert.strictEqual(result.sku, `LTD-${s}`);

    const row = await query(`SELECT * FROM sku_group WHERE sku = $1`, [`LTD-${s}`]);
    assert.strictEqual(row.rows.length, 1);
    assert.strictEqual(row.rows[0].description, "happy path");
    assert.strictEqual(row.rows[0].archived_at, null);
  });

  test("createLtdEdition rejects duplicate slug with EditionConflictError", async (t) => {
    const s = slug("DUPE");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "first" });
    await assert.rejects(
      () => createLtdEdition({ slug: s, description: "second" }),
      (e) => e instanceof EditionConflictError
    );
  });

  test("createLtdEdition trims description whitespace", async (t) => {
    const s = slug("TRIM");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "  spaces around  " });
    const row = await query(`SELECT description FROM sku_group WHERE sku = $1`, [`LTD-${s}`]);
    assert.strictEqual(row.rows[0].description, "spaces around");
  });

  // ───────────────────────────────────────────────────────────────────
  // getEdition — shape contract
  // ───────────────────────────────────────────────────────────────────

  test("getEdition returns null for unknown sku", async () => {
    const result = await getEdition("LTD-DOESNOTEXIST");
    assert.strictEqual(result, null);
  });

  test("getEdition returns null for non-LTD sku", async () => {
    // GL is a real catalog group SKU; getEdition should not return it
    // because it's not LTD-shaped.
    const result = await getEdition("GL");
    assert.strictEqual(result, null);
  });

  test("getEdition returns expected shape for live edition", async (t) => {
    const s = slug("SHAPE");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "shape test" });
    const ed = await getEdition(`LTD-${s}`);
    assert.notStrictEqual(ed, null);
    assert.strictEqual(ed.sku, `LTD-${s}`);
    assert.strictEqual(ed.slug, s);
    assert.strictEqual(ed.description, "shape test");
    assert.strictEqual(ed.active, true);
    assert.strictEqual(ed.archived_at, null);
    assert.strictEqual(ed.cable_count, 0);
    // No prefix on edition (LTD spans series).
    assert.strictEqual(ed.prefix, undefined);
  });

  // ───────────────────────────────────────────────────────────────────
  // updateEdition — validation, archive toggle, description edit
  // ───────────────────────────────────────────────────────────────────

  test("updateEdition rejects unknown sku with EditionValidationError", async () => {
    await assert.rejects(
      () => updateEdition("LTD-NOTREAL", { description: "x" }),
      (e) => e instanceof EditionValidationError && e.field === "sku"
    );
  });

  test("updateEdition rejects empty description", async (t) => {
    const s = slug("EMPTY");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "real" });
    await assert.rejects(
      () => updateEdition(`LTD-${s}`, { description: "" }),
      (e) => e instanceof EditionValidationError && e.field === "description"
    );
  });

  test("updateEdition archive sets archived_at and unarchive clears it", async (t) => {
    const s = slug("ARCH");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "for archive" });

    const archived = await updateEdition(`LTD-${s}`, { active: false });
    assert.strictEqual(archived.active, false);
    assert.notStrictEqual(archived.archived_at, null);

    const reactivated = await updateEdition(`LTD-${s}`, { active: true });
    assert.strictEqual(reactivated.active, true);
    assert.strictEqual(reactivated.archived_at, null);
  });

  test("updateEdition no-ops when description unchanged", async (t) => {
    const s = slug("NOOP");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "same" });
    const result = await updateEdition(`LTD-${s}`, { description: "same" });
    assert.strictEqual(result.description, "same");
  });

  test("updateEdition trims description whitespace", async (t) => {
    const s = slug("TRIME");
    t.after(() => deleteIfExists(`LTD-${s}`));

    await createLtdEdition({ slug: s, description: "before" });
    const result = await updateEdition(`LTD-${s}`, { description: "  after  " });
    assert.strictEqual(result.description, "after");
  });

  // ───────────────────────────────────────────────────────────────────
  // listEditions — filter behavior
  // ───────────────────────────────────────────────────────────────────

  test("listEditions filters: active vs archived vs all", async (t) => {
    const sActive = slug("LACTV");
    const sArchived = slug("LARCH");
    t.after(async () => {
      await deleteIfExists(`LTD-${sActive}`);
      await deleteIfExists(`LTD-${sArchived}`);
    });

    await createLtdEdition({ slug: sActive, description: "active" });
    await createLtdEdition({ slug: sArchived, description: "archived" });
    await updateEdition(`LTD-${sArchived}`, { active: false });

    const active = await listEditions("active");
    assert.ok(active.some((e) => e.sku === `LTD-${sActive}`),
      `LTD-${sActive} expected in active list`);
    assert.ok(!active.some((e) => e.sku === `LTD-${sArchived}`),
      `LTD-${sArchived} not expected in active list`);

    const archived = await listEditions("archived");
    assert.ok(archived.some((e) => e.sku === `LTD-${sArchived}`),
      `LTD-${sArchived} expected in archived list`);
    assert.ok(!archived.some((e) => e.sku === `LTD-${sActive}`),
      `LTD-${sActive} not expected in archived list`);

    const all = await listEditions("all");
    assert.ok(all.some((e) => e.sku === `LTD-${sActive}`));
    assert.ok(all.some((e) => e.sku === `LTD-${sArchived}`));
  });

  test("listEditions only returns LTD-shaped sku_group rows", async () => {
    const all = await listEditions("all");
    for (const e of all) {
      assert.match(e.sku, /^LTD-[A-Z0-9]{4,24}$/,
        `unexpected non-LTD sku in listEditions: ${e.sku}`);
    }
  });

  // Final defensive cleanup in case any test orphaned a row.
  after(async () => {
    await query(`DELETE FROM sku_group WHERE sku LIKE $1`, [`LTD-${RUN_TAG}%`]);
  });
}
