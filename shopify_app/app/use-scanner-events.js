import { useEffect, useState } from "react";

/**
 * Receive scanner events via polling. SSE is blocked in the Shopify iframe
 * so we poll /api/scanner-events at 500ms intervals while `enabled` is true.
 *
 * Returns the most recent { serial, timestamp } event seen, or null. The
 * timestamp is the server's clock — useEffect dependency on event.timestamp
 * lets callers detect "new event" without re-firing on stale state.
 */
export function useScannerEvents(enabled) {
  const [lastScanEvent, setLastScanEvent] = useState(null);
  const [lastTimestamp, setLastTimestamp] = useState(0);

  useEffect(() => {
    if (!enabled) return;

    const interval = setInterval(async () => {
      try {
        const response = await fetch(`/api/scanner-events?since=${lastTimestamp}`);
        const data = await response.json();
        if (data.serial && data.timestamp > lastTimestamp) {
          setLastScanEvent({ serial: data.serial, timestamp: data.timestamp });
          setLastTimestamp(data.timestamp);
        }
      } catch (error) {
        // Silently fail; will retry on next interval.
      }
    }, 500);

    return () => clearInterval(interval);
  }, [lastTimestamp, enabled]);

  return lastScanEvent;
}
