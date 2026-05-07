/**
 * JSON Schema definitions for the YAML config files loaded at app startup.
 *
 * Validated by cable-config.server.js via ajv. Failures throw at module
 * init — fail fast with a clear message rather than letting a malformed
 * YAML produce silent gaps in the resolver later.
 *
 * Schemas are intentionally strict: additionalProperties=true on the
 * top-level container so back-office or comment-only fields don't trip
 * validation, but the per-entry shape is locked down so a typo in code
 * or display gets caught immediately.
 */

export const PATTERNS_SCHEMA = {
  type: "object",
  required: ["patterns"],
  properties: {
    patterns: {
      type: "array",
      items: {
        type: "object",
        required: ["code", "name", "fabric_type"],
        properties: {
          code: { type: "string", pattern: "^[A-Z]{2,3}$" },
          name: { type: "string", minLength: 1 },
          fabric_type: { type: "string", enum: ["rayon", "cotton"] },
          description: { type: "string" },
        },
        additionalProperties: false,
      },
    },
  },
};

export const CABLE_LINES_SCHEMA = {
  type: "object",
  required: ["series"],
  properties: {
    series: {
      type: "array",
      items: {
        type: "object",
        required: [
          "sku_prefix",
          "product_line",
          "core_cable",
          "braid_material",
          "lengths",
          "connectors",
        ],
        properties: {
          sku_prefix: { type: "string", pattern: "^[A-Z]{2,3}$" },
          product_line: { type: "string", minLength: 1 },
          core_cable: { type: "string", minLength: 1 },
          braid_material: { type: "string", enum: ["Rayon", "Cotton"] },
          lengths: {
            type: "array",
            items: { type: "number", exclusiveMinimum: 0 },
            minItems: 1,
          },
          connectors: {
            type: "array",
            minItems: 1,
            items: {
              type: "object",
              required: ["code", "display"],
              properties: {
                code: { type: "string" }, // '' or '-R' etc.
                display: { type: "string", minLength: 1 },
              },
              additionalProperties: false,
            },
          },
        },
        additionalProperties: false,
      },
    },
  },
};
