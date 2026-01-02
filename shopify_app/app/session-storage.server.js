import { query } from "./db.server.js";
import { Session } from "@shopify/shopify-api";

// Custom PostgreSQL session storage using our existing database connection
class CustomPostgreSQLSessionStorage {
  constructor() {
    this.ready = this.init();
  }

  async init() {
    // Create the shopify_sessions table if it doesn't exist
    await query(`
      CREATE TABLE IF NOT EXISTS shopify_sessions (
        id VARCHAR(255) PRIMARY KEY,
        shop VARCHAR(255) NOT NULL,
        state VARCHAR(255) NOT NULL,
        is_online BOOLEAN NOT NULL,
        scope VARCHAR(1024),
        expires TIMESTAMPTZ,
        access_token VARCHAR(255) NOT NULL,
        user_id BIGINT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
      )
    `);

    // Create index on shop for faster lookups
    await query(`
      CREATE INDEX IF NOT EXISTS idx_shopify_sessions_shop
      ON shopify_sessions(shop)
    `);
  }

  async storeSession(session) {
    await this.ready;

    try {
      await query(
        `INSERT INTO shopify_sessions (id, shop, state, is_online, scope, expires, access_token, user_id, updated_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
         ON CONFLICT (id)
         DO UPDATE SET
           shop = EXCLUDED.shop,
           state = EXCLUDED.state,
           is_online = EXCLUDED.is_online,
           scope = EXCLUDED.scope,
           expires = EXCLUDED.expires,
           access_token = EXCLUDED.access_token,
           user_id = EXCLUDED.user_id,
           updated_at = NOW()`,
        [
          session.id,
          session.shop,
          session.state,
          session.isOnline,
          session.scope,
          session.expires ? new Date(session.expires) : null,
          session.accessToken,
          session.onlineAccessInfo?.associated_user?.id || null,
        ]
      );
      return true;
    } catch (error) {
      console.error("Error storing session:", error);
      return false;
    }
  }

  async loadSession(id) {
    await this.ready;

    try {
      const result = await query(
        `SELECT * FROM shopify_sessions WHERE id = $1`,
        [id]
      );

      if (result.rows.length === 0) {
        return undefined;
      }

      const row = result.rows[0];

      // Reconstruct Session object
      const sessionData = {
        id: row.id,
        shop: row.shop,
        state: row.state,
        isOnline: row.is_online,
        scope: row.scope,
        accessToken: row.access_token,
      };

      if (row.expires) {
        sessionData.expires = new Date(row.expires);
      }

      if (row.user_id) {
        sessionData.onlineAccessInfo = {
          associated_user: {
            id: row.user_id,
          },
        };
      }

      // Return a proper Session instance
      return new Session(sessionData);
    } catch (error) {
      console.error("Error loading session:", error);
      return undefined;
    }
  }

  async deleteSession(id) {
    await this.ready;

    try {
      await query(
        `DELETE FROM shopify_sessions WHERE id = $1`,
        [id]
      );
      return true;
    } catch (error) {
      console.error("Error deleting session:", error);
      return false;
    }
  }

  async deleteSessions(ids) {
    await this.ready;

    try {
      await query(
        `DELETE FROM shopify_sessions WHERE id = ANY($1)`,
        [ids]
      );
      return true;
    } catch (error) {
      console.error("Error deleting sessions:", error);
      return false;
    }
  }

  async findSessionsByShop(shop) {
    await this.ready;

    try {
      const result = await query(
        `SELECT * FROM shopify_sessions WHERE shop = $1`,
        [shop]
      );

      return result.rows.map(row => {
        const sessionData = {
          id: row.id,
          shop: row.shop,
          state: row.state,
          isOnline: row.is_online,
          scope: row.scope,
          accessToken: row.access_token,
        };

        if (row.expires) {
          sessionData.expires = new Date(row.expires);
        }

        if (row.user_id) {
          sessionData.onlineAccessInfo = {
            associated_user: {
              id: row.user_id,
            },
          };
        }

        // Return a proper Session instance
        return new Session(sessionData);
      });
    } catch (error) {
      console.error("Error finding sessions by shop:", error);
      return [];
    }
  }
}

export default new CustomPostgreSQLSessionStorage();
