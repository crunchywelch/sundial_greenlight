/**
 * MQTT client module - subscribes to barcode scanners on each Pi via SSH tunnels.
 *
 * Connects to each Pi's Mosquitto broker (reverse-tunneled to localhost ports).
 * Subscribes to:
 *   scanner/barcode  - scan events
 *   scanner/status   - Greenlight state (idle/scanning/offline)
 *
 * Env var: MQTT_HOSTS=greenlightpi1:18831,greenlightpi2:18832
 */

import mqtt from "mqtt";

// Per-host state
const hosts = new Map(); // name -> { client, status, lastScan }

// Global last scan event (consumed by api.scanner-events and api.order-fulfillment)
let lastScanEvent = null;

function parseHostsConfig() {
  const raw = process.env.MQTT_HOSTS || "";
  if (!raw) return [];
  return raw.split(",").map((entry) => {
    const [name, port] = entry.trim().split(":");
    return { name, port: parseInt(port) };
  });
}

function connectToHost({ name, port }) {
  const url = `mqtt://localhost:${port}`;
  console.log(`[mqtt] Connecting to ${name} at ${url}`);

  const client = mqtt.connect(url, {
    clientId: `shopify-app-${name}-${Date.now() % 10000}`,
    reconnectPeriod: 5000,
    connectTimeout: 10000,
    will: undefined, // we're a subscriber, no will needed
  });

  const state = {
    client,
    name,
    port,
    status: { state: "connecting" },
    connected: false,
  };

  hosts.set(name, state);

  client.on("connect", () => {
    console.log(`[mqtt] Connected to ${name}`);
    state.connected = true;
    client.subscribe(["scanner/barcode", "scanner/status"], { qos: 1 });
  });

  client.on("close", () => {
    state.connected = false;
    state.status = { state: "disconnected" };
  });

  client.on("error", (err) => {
    console.error(`[mqtt] Error on ${name}:`, err.message);
  });

  client.on("message", (topic, payload) => {
    try {
      const data = JSON.parse(payload.toString());

      if (topic === "scanner/status") {
        state.status = data;
        console.log(`[mqtt] ${name} status: ${JSON.stringify(data)}`);
      }

      if (topic === "scanner/barcode") {
        const serial = data.barcode;
        if (serial) {
          lastScanEvent = {
            serial: serial.trim().replace(/[\x00-\x1F\x7F]/g, ""),
            timestamp: Date.now(),
            host: name,
          };
          console.log(
            `[mqtt] Scan from ${name}: "${lastScanEvent.serial}"`,
          );
        }
      }
    } catch (err) {
      console.error(`[mqtt] Bad message from ${name}:`, err.message);
    }
  });

  return state;
}

// Initialize on first import (Remix server-side module)
let initialized = false;

function ensureInitialized() {
  if (initialized) return;
  initialized = true;

  const hostConfigs = parseHostsConfig();
  if (hostConfigs.length === 0) {
    console.log("[mqtt] No MQTT_HOSTS configured, scanner events disabled");
    return;
  }

  console.log(
    `[mqtt] Connecting to ${hostConfigs.length} scanner host(s): ${hostConfigs.map((h) => h.name).join(", ")}`,
  );
  for (const config of hostConfigs) {
    connectToHost(config);
  }
}

ensureInitialized();

/**
 * Get the most recent scan event (replaces webhook-based ingestion).
 */
export function getLastScanEvent() {
  return lastScanEvent;
}

/**
 * Get scanner status for all hosts.
 * Returns array of { name, connected, status }.
 */
export function getScannerStatus() {
  const result = [];
  for (const [name, state] of hosts) {
    result.push({
      name,
      connected: state.connected,
      status: state.status,
    });
  }
  return result;
}

/**
 * Get hosts where Greenlight is actively scanning.
 * Returns array of host names.
 */
export function getActiveGreenlightHosts() {
  const active = [];
  for (const [name, state] of hosts) {
    if (state.status?.state === "scanning") {
      active.push(state.status.host || name);
    }
  }
  return active;
}
