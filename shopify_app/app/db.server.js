import pg from "pg";

const { Pool } = pg;

let pool;

function getPool() {
  if (!pool) {
    pool = new Pool({
      user: process.env.PGUSER,
      password: process.env.PGPASSWORD,
      host: process.env.PGHOST,
      database: process.env.PGDATABASE,
      port: parseInt(process.env.PGPORT || "5432"),
      ssl: process.env.PGSSLMODE === "require" ? { rejectUnauthorized: false } : false,
      max: 20,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 2000,
    });

    pool.on("error", (err) => {
      console.error("Unexpected error on idle client", err);
    });
  }

  return pool;
}

export async function query(text, params) {
  const pool = getPool();
  const start = Date.now();
  try {
    const res = await pool.query(text, params);
    const duration = Date.now() - start;
    console.log("Executed query", { text, duration, rows: res.rowCount });
    return res;
  } catch (error) {
    console.error("Database query error:", error);
    throw error;
  }
}

export async function getClient() {
  const pool = getPool();
  return await pool.connect();
}

/**
 * Append a row to the cable_events audit trail on an existing transaction
 * `client`, so the event commits (or rolls back) atomically with the mutation
 * it describes — a separate connection could log a phantom event after the
 * mutation rolls back. The insert is wrapped in a SAVEPOINT so an audit-write
 * failure (e.g. a bad FK) rolls back alone and leaves the caller's transaction
 * usable, letting the real mutation still commit. Contract shared with the
 * Greenlight side (see docs/WHOLESALE_ATTRIBUTION.md / cable_events):
 * event is free text, actor is 'admin'/'buyer' here vs an operator code there,
 * detail is conventionally { from, to, ... }.
 */
export async function recordCableEvent(client, { serialNumber, event, actor = null, detail = null }) {
  await client.query("SAVEPOINT cable_event");
  try {
    await client.query(
      `INSERT INTO cable_events (serial_number, event, actor, detail)
       VALUES ($1, $2, $3, $4)`,
      [serialNumber, event, actor, detail ? JSON.stringify(detail) : null]
    );
    await client.query("RELEASE SAVEPOINT cable_event");
  } catch (error) {
    await client.query("ROLLBACK TO SAVEPOINT cable_event");
    console.error("cable_events audit write failed:", error.message);
  }
}

export default { query, getClient, recordCableEvent };
