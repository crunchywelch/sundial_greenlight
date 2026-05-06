/**
 * LTD edition constants and pure helpers safe to import from both server
 * (loaders/actions) and client (route components). No DB or server-only
 * dependencies belong here — anything imported from `editions.server.js`
 * gets stripped from the client bundle.
 */

export const SLUG_PATTERN = /^[A-Z0-9]{4,24}$/;
