/**
 * LTD edition CRUD against the Phase 5 sku_group schema.
 *
 * sku_group: just (sku, description, archived_at). LTD groups are
 * series-agnostic (`LTD-PHISH26`); a single edition can contain cables of
 * any series. Per-cable variation (prefix, length, connector) lives on
 * audio_cables.
 *
 * Per-edition Shopify product creation is paused pending a design decision
 * about how LTD editions are sold (single multi-variant product vs. catalog
 * cables tagged with the edition slug).
 */

import { query } from "./db.server.js";
import { SLUG_PATTERN } from "./editions-shared.js";
import { parseGroupSku } from "./cable-config.server.js";

export { SLUG_PATTERN };

export class EditionValidationError extends Error {
  constructor(message, field) {
    super(message);
    this.name = "EditionValidationError";
    this.field = field;
  }
}

export class EditionConflictError extends Error {
  constructor(message) {
    super(message);
    this.name = "EditionConflictError";
  }
}

function validateCreateInput({ slug, description }) {
  if (!slug || !SLUG_PATTERN.test(slug)) {
    throw new EditionValidationError("Slug must be 4–24 characters, A–Z and 0–9 only.", "slug");
  }
  if (!description || !description.trim()) {
    throw new EditionValidationError("Description is required.", "description");
  }
}

/**
 * Create an LTD edition. Inserts a single sku_group row with sku=`LTD-{slug}`.
 *
 * Returns { sku } on success.
 * Throws EditionValidationError for bad input,
 * EditionConflictError if the slug already exists.
 */
export async function createLtdEdition({ slug, description }) {
  validateCreateInput({ slug, description });

  const sku = `LTD-${slug}`;

  try {
    await query(
      `INSERT INTO sku_group (sku, description) VALUES ($1, $2)`,
      [sku, description.trim()]
    );
    return { sku };
  } catch (e) {
    if (e.code === "23505") {
      throw new EditionConflictError(`Edition ${sku} already exists.`);
    }
    throw e;
  }
}

/**
 * Fetch a single LTD edition with cable count. Returns null if not found
 * or not an LTD-shaped sku.
 */
export async function getEdition(sku) {
  const result = await query(
    `SELECT sg.sku, sg.description, sg.archived_at,
            (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
     FROM sku_group sg
     WHERE sg.sku = $1 AND sg.sku ~ '^LTD-[A-Z0-9]{4,24}$'`,
    [sku]
  );
  if (result.rows.length === 0) return null;
  const r = result.rows[0];
  const parsed = parseGroupSku(r.sku);
  return {
    sku: r.sku,
    slug: parsed.slug ?? null,
    description: r.description,
    archived_at: r.archived_at,
    active: r.archived_at === null,
    cable_count: parseInt(r.cable_count, 10),
  };
}

/**
 * List LTD editions with cable counts.
 * filter: 'active' | 'archived' | 'all'
 */
export async function listEditions(filter = "active") {
  const where = ["sg.sku ~ '^LTD-[A-Z0-9]{4,24}$'"];
  if (filter === "active") where.push("sg.archived_at IS NULL");
  else if (filter === "archived") where.push("sg.archived_at IS NOT NULL");

  const result = await query(
    `SELECT sg.sku, sg.description, sg.archived_at,
            (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku_group = sg.sku) AS cable_count
     FROM sku_group sg
     WHERE ${where.join(" AND ")}
     ORDER BY (sg.archived_at IS NULL) DESC, sg.sku`
  );

  return result.rows.map((r) => {
    const parsed = parseGroupSku(r.sku);
    return {
      sku: r.sku,
      slug: parsed.slug ?? null,
      description: r.description,
      archived_at: r.archived_at,
      active: r.archived_at === null,
      cable_count: parseInt(r.cable_count, 10),
    };
  });
}

/**
 * Update an edition. Editable fields: description, active.
 *
 * Slug is part of the SKU (primary key) and isn't editable — there's no
 * UI for it. Description stays editable regardless of how many cables
 * are registered against the edition.
 */
export async function updateEdition(sku, updates) {
  const existing = await getEdition(sku);
  if (!existing) throw new EditionValidationError(`Edition ${sku} not found.`, "sku");

  const updateClauses = [];
  const values = [];

  if (updates.description !== undefined) {
    const next = (updates.description ?? "").trim();
    const prev = (existing.description ?? "").trim();
    if (next !== prev) {
      if (!next) {
        throw new EditionValidationError("Description is required.", "description");
      }
      updateClauses.push(`description = $${values.length + 1}`);
      values.push(next);
    }
  }

  if (updates.active != null) {
    // archived_at is the source of truth — no separate active column.
    updateClauses.push(`archived_at = ${updates.active ? "NULL" : "CURRENT_TIMESTAMP"}`);
  }

  if (updateClauses.length > 0) {
    await query(
      `UPDATE sku_group SET ${updateClauses.join(", ")} WHERE sku = $${values.length + 1}`,
      [...values, sku]
    );
  }

  return getEdition(sku);
}
