import { shopifyApp } from "@shopify/shopify-app-remix/server";
import { restResources } from "@shopify/shopify-api/rest/admin/2025-07";

// Simple in-memory session storage (not for production use - use database-backed storage)
const sessions = new Map();

const customSessionStorage = {
  async storeSession(session) {
    sessions.set(session.id, session);
    return true;
  },
  async loadSession(id) {
    return sessions.get(id) || null;
  },
  async deleteSession(id) {
    sessions.delete(id);
    return true;
  },
  async deleteSessions(ids) {
    ids.forEach(id => sessions.delete(id));
    return true;
  },
  async findSessionsByShop(shop) {
    return Array.from(sessions.values()).filter(session => session.shop === shop);
  },
};

const shopify = shopifyApp({
  apiKey: process.env.SHOPIFY_API_KEY,
  apiSecretKey: process.env.SHOPIFY_API_SECRET || "",
  apiVersion: "2025-07",
  scopes: process.env.SHOPIFY_SCOPES?.split(","),
  appUrl: process.env.SHOPIFY_APP_URL || "",
  sessionStorage: customSessionStorage,
  restResources,
  isEmbeddedApp: true,
  authPathPrefix: "/auth",
});

export default shopify;
export const apiVersion = "2025-07";
export const addDocumentResponseHeaders = shopify.addDocumentResponseHeaders;
export const authenticate = shopify.authenticate;
export const unauthenticated = shopify.unauthenticated;
export const login = shopify.login;
export const registerWebhooks = shopify.registerWebhooks;
export const sessionStorage = shopify.sessionStorage;
