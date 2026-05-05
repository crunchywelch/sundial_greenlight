import { getClient, query } from "./db.server.js";
import { SLUG_PATTERN, parseLtdSku } from "./editions-shared.js";
import { seriesForPrefix, seriesDataForPrefix, parseSku } from "./cable-config.server.js";

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

/** Validate inputs for creating an edition. Throws EditionValidationError. */
function validateCreateInput({ seriesPrefix, slug, lengthFt, description, eventName }) {
  if (!seriesPrefix || !/^[A-Z]+$/.test(seriesPrefix)) {
    throw new EditionValidationError("Series prefix is required.", "seriesPrefix");
  }
  if (!slug || !SLUG_PATTERN.test(slug)) {
    throw new EditionValidationError("Slug must be 4–12 characters, A–Z and 0–9 only.", "slug");
  }
  const len = parseFloat(lengthFt);
  if (!Number.isFinite(len) || len <= 0) {
    throw new EditionValidationError("Length must be a positive number.", "lengthFt");
  }
  if (!eventName || !eventName.trim()) {
    throw new EditionValidationError("Event name is required.", "eventName");
  }
  if (description != null && typeof description !== "string") {
    throw new EditionValidationError("Description must be a string.", "description");
  }
}

/**
 * Create an LTD edition atomically:
 *   1. Insert cable_skus row — minimal columns: sku, length, description.
 *      Series / core_cable / braid_material / connector_type are derived
 *      at read time from the SKU + YAML config; not stored.
 *   2. Insert cable_ltd_metadata sidecar.
 * All in one transaction. Returns { sku, series } on success.
 *
 * Throws EditionValidationError for bad input (including unknown series
 * prefix), EditionConflictError if the slug already exists, or generic
 * Error for unexpected failures.
 */
export async function createLtdEdition({ seriesPrefix, slug, lengthFt, description, eventName, createdBy, notes }) {
  validateCreateInput({ seriesPrefix, slug, lengthFt, description, eventName });

  const series = seriesForPrefix(seriesPrefix);
  if (!series) {
    throw new EditionValidationError(`Unknown series prefix '${seriesPrefix}'.`, "seriesPrefix");
  }

  const sku = `${seriesPrefix}-LTD-${slug}`;
  const len = parseFloat(lengthFt);

  const client = await getClient();
  try {
    await client.query("BEGIN");

    await client.query(
      `INSERT INTO cable_skus (sku, length, description)
       VALUES ($1, $2, $3)`,
      [sku, len, description || null]
    );

    await client.query(
      `INSERT INTO cable_ltd_metadata (sku, event_name, created_by, notes)
       VALUES ($1, $2, $3, $4)`,
      [sku, eventName.trim(), createdBy || null, notes ? notes.trim() : null]
    );

    await client.query("COMMIT");
    return { sku, series };
  } catch (e) {
    await client.query("ROLLBACK");
    if (e.code === "23505") {
      throw new EditionConflictError(`SKU ${sku} already exists.`);
    }
    throw e;
  } finally {
    client.release();
  }
}

/**
 * Fetch a single edition with cable count. Returns null if not found.
 *
 * series/core_cable/braid_material/connector_type are resolved from YAML
 * via the cable-config resolver — not read from cable_skus columns. The
 * returned shape stays the same so consumers (admin UI, Shopify product
 * helpers) don't have to know whether a field came from the DB or YAML.
 */
export async function getEdition(sku) {
  const result = await query(
    `SELECT cs.sku, cs.length, cs.description,
            lm.event_name, lm.archived_at, lm.created_by, lm.notes, lm.created_at,
            (SELECT COUNT(*) FROM audio_cables ac WHERE ac.sku = cs.sku) AS cable_count
     FROM cable_skus cs
     JOIN cable_ltd_metadata lm ON lm.sku = cs.sku
     WHERE cs.sku = $1`,
    [sku]
  );
  if (result.rows.length === 0) return null;
  const r = result.rows[0];

  const parsed = parseSku(r.sku);
  const seriesData = parsed.series_prefix ? seriesDataForPrefix(parsed.series_prefix) : null;
  const defaultConnector = seriesData?.connectors?.find((c) => (c.code ?? "") === "")?.display
    ?? seriesData?.connectors?.[0]?.display
    ?? null;

  return {
    sku: r.sku,
    slug: parsed.slug ?? r.sku.split("-").slice(-1)[0],
    series: parsed.series,
    core_cable: seriesData?.core_cable ?? null,
    braid_material: seriesData?.braid_material ?? null,
    color_pattern: "Limited Edition",
    length: r.length,
    connector_type: defaultConnector,
    description: r.description,
    event_name: r.event_name,
    active: r.archived_at === null,
    archived_at: r.archived_at,
    created_by: r.created_by,
    notes: r.notes,
    created_at: r.created_at,
    cable_count: parseInt(r.cable_count, 10),
  };
}

/**
 * Update an edition. Always-editable fields: event_name, notes, active.
 * Locked fields (description, length): rejected if cable_count > 0.
 * Returns the updated edition.
 */
export async function updateEdition(sku, updates) {
  const existing = await getEdition(sku);
  if (!existing) throw new EditionValidationError(`Edition ${sku} not found.`, "sku");

  const locked = existing.cable_count > 0;
  const csUpdates = [];
  const csValues = [];
  const lmUpdates = [];
  const lmValues = [];

  if (updates.eventName != null) {
    if (!updates.eventName.trim()) throw new EditionValidationError("Event name is required.", "eventName");
    lmUpdates.push(`event_name = $${lmValues.length + 1}`);
    lmValues.push(updates.eventName.trim());
  }
  if (updates.notes !== undefined) {
    lmUpdates.push(`notes = $${lmValues.length + 1}`);
    lmValues.push(updates.notes ? updates.notes.trim() : null);
  }
  if (updates.active != null) {
    // archived_at is the source of truth — there's no separate active column.
    lmUpdates.push(`archived_at = ${updates.active ? "NULL" : "CURRENT_TIMESTAMP"}`);
  }

  if (updates.description !== undefined) {
    if (locked && updates.description !== existing.description) {
      throw new EditionValidationError("Description is locked once cables are registered.", "description");
    }
    if (updates.description !== existing.description) {
      csUpdates.push(`description = $${csValues.length + 1}`);
      csValues.push(updates.description || null);
    }
  }
  if (updates.lengthFt != null) {
    const len = parseFloat(updates.lengthFt);
    if (!Number.isFinite(len) || len <= 0) {
      throw new EditionValidationError("Length must be a positive number.", "lengthFt");
    }
    if (Number(len) !== Number(existing.length)) {
      if (locked) throw new EditionValidationError("Length is locked once cables are registered.", "lengthFt");
      csUpdates.push(`length = $${csValues.length + 1}`);
      csValues.push(len);
    }
  }

  const client = await getClient();
  try {
    await client.query("BEGIN");
    if (csUpdates.length > 0) {
      csUpdates.push(`updated_at = CURRENT_TIMESTAMP`);
      await client.query(
        `UPDATE cable_skus SET ${csUpdates.join(", ")} WHERE sku = $${csValues.length + 1}`,
        [...csValues, sku]
      );
    }
    if (lmUpdates.length > 0) {
      await client.query(
        `UPDATE cable_ltd_metadata SET ${lmUpdates.join(", ")} WHERE sku = $${lmValues.length + 1}`,
        [...lmValues, sku]
      );
    }
    await client.query("COMMIT");
  } catch (e) {
    await client.query("ROLLBACK");
    throw e;
  } finally {
    client.release();
  }

  return getEdition(sku);
}
