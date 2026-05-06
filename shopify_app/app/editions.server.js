/**
 * LTD edition CRUD against the post-Phase-4 sku_group schema.
 *
 * sku_group: just (sku, description, archived_at). No length, no event_name,
 * no notes, no created_by — all pruned in Phase 4. Cables registered against
 * an LTD edition carry their own length and connector_code on audio_cables.
 *
 * Per-edition Shopify product creation is paused pending a design decision
 * about how LTD editions are sold (single multi-variant product vs. catalog
 * cables tagged with the edition slug). The new-edition action no longer
 * creates a Shopify product automatically.
 */

import { query } from "./db.server.js";
import { SLUG_PATTERN, parseLtdSku } from "./editions-shared.js";
import { seriesForPrefix, parseGroupSku } from "./cable-config.server.js";

// Re-export so existing server-side imports keep working.
export { SLUG_PATTERN, parseLtdSku };

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

function validateCreateInput({ seriesPrefix, slug, description }) {
  if (!seriesPrefix || !/^[A-Z]+$/.test(seriesPrefix)) {
    throw new EditionValidationError("Series prefix is required.", "seriesPrefix");
  }
  if (!slug || !SLUG_PATTERN.test(slug)) {
    throw new EditionValidationError("Slug must be 4–12 characters, A–Z and 0–9 only.", "slug");
  }
  if (!description || !description.trim()) {
    throw new EditionValidationError("Description is required.", "description");
  }
}

/**
 * Create an LTD edition. Inserts a single sku_group row.
 *
 * Returns { sku, series } on success.
 * Throws EditionValidationError for bad input (including unknown series prefix),
 * EditionConflictError if the slug already exists.
 */
export async function createLtdEdition({ seriesPrefix, slug, description }) {
  validateCreateInput({ seriesPrefix, slug, description });

  const series = seriesForPrefix(seriesPrefix);
  if (!series) {
    throw new EditionValidationError(`Unknown series prefix '${seriesPrefix}'.`, "seriesPrefix");
  }

  const sku = `${seriesPrefix}-LTD-${slug}`;

  try {
    await query(
      `INSERT INTO sku_group (sku, description) VALUES ($1, $2)`,
      [sku, description.trim()]
    );
    return { sku, series };
  } catch (e) {
    if (e.code === "23505") {
      throw new EditionConflictError(`SKU ${sku} already exists.`);
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
     WHERE sg.sku = $1 AND sg.sku ~ '-LTD-[A-Z0-9]{4,12}$'`,
    [sku]
  );
  if (result.rows.length === 0) return null;
  const r = result.rows[0];
  const parsed = parseGroupSku(r.sku);
  return {
    sku: r.sku,
    slug: parsed.slug ?? null,
    prefix: parsed.prefix,
    series: parsed.series,
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
  const where = ["sg.sku ~ '-LTD-[A-Z0-9]{4,12}$'"];
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
      prefix: parsed.prefix,
      series: parsed.series,
      description: r.description,
      archived_at: r.archived_at,
      active: r.archived_at === null,
      cable_count: parseInt(r.cable_count, 10),
    };
  });
}

/**
 * Update an edition. Editable fields: description, active.
 * description is locked once any cables are registered against the edition.
 */
export async function updateEdition(sku, updates) {
  const existing = await getEdition(sku);
  if (!existing) throw new EditionValidationError(`Edition ${sku} not found.`, "sku");

  const locked = existing.cable_count > 0;
  const updateClauses = [];
  const values = [];

  if (updates.description !== undefined) {
    const next = (updates.description ?? "").trim();
    const prev = (existing.description ?? "").trim();
    if (next !== prev) {
      if (locked) {
        throw new EditionValidationError("Description is locked once cables are registered.", "description");
      }
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
