import { useEffect, useState } from "react";
import { useNavigate, useLocation } from "@remix-run/react";
import { useScannerEvents } from "../use-scanner-events";

/**
 * Serial lookup box for the cable detail page: type a serial or scan one (the
 * Zebra scanner's events are bridged from Greenlight over MQTT and polled via
 * useScannerEvents while the input is focused). Either way, navigate to the
 * cable's detail page. Search params are preserved so the embedded-app host
 * param flows across the navigation.
 */
export function CableLookup({ defaultValue = "" }) {
  const [serial, setSerial] = useState(defaultValue);
  const [focused, setFocused] = useState(false);
  const [scannerActive, setScannerActive] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const scanEvent = useScannerEvents(focused);

  const go = (value) => {
    const trimmed = (value || "").trim();
    if (!trimmed) return;
    navigate({ pathname: `/app/cables/serial/${encodeURIComponent(trimmed)}`, search: location.search });
  };

  useEffect(() => {
    if (scanEvent?.serial) {
      setSerial(scanEvent.serial);
      setScannerActive(true);
      setTimeout(() => setScannerActive(false), 2000);
      go(scanEvent.serial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanEvent?.timestamp]);

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); go(serial); }}
      style={{ border: "1px solid #ddd", borderRadius: "8px", padding: "16px", backgroundColor: "#fff", marginBottom: "20px" }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
        <label style={{ fontSize: "14px", fontWeight: "bold" }}>Scan or type a serial number</label>
        {scannerActive && (
          <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "#008060", fontSize: "13px", fontWeight: "bold" }}>
            <div style={{ width: "8px", height: "8px", borderRadius: "50%", backgroundColor: "#008060", animation: "pulse 1s infinite" }}></div>
            Scanner active
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: "10px" }}>
        <input
          type="text"
          value={serial}
          onChange={(e) => setSerial(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="e.g. 000517"
          autoFocus
          style={{
            flex: 1,
            padding: "10px",
            border: scannerActive ? "2px solid #008060" : "1px solid #ccc",
            borderRadius: "4px",
            fontSize: "14px",
            backgroundColor: scannerActive ? "#f0f9ff" : "#fff",
          }}
        />
        <button type="submit" style={{ padding: "10px 20px", backgroundColor: "#008060", color: "#fff", border: "none", borderRadius: "4px", cursor: "pointer", fontSize: "14px", fontWeight: "bold" }}>
          Look up
        </button>
      </div>
    </form>
  );
}
