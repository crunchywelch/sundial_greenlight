# Capacitance Test Circuit Design

## Overview

Measures cable capacitance using the RC time constant method. The cable acts as a capacitor between tip and sleeve conductors. We charge it through a known resistor and measure the time to reach 50% of Vcc.

## Circuit Schematic

```
                                    CABLE UNDER TEST
                                 ┌──────────────────────┐
                                 │   (capacitance)      │
    Arduino                      │                      │
    ┌─────────┐                  │                      │
    │         │                  │                      │
    │  D7 ────┼──[2.2MΩ]──┬──────┼── TIP      SLEEVE ──┼──┬── GND (via K1+K2)
    │         │           │      │                      │  │
    │  D8  ───┼──[1kΩ]────┤      └──────────────────────┘  │
    │         │           │                                │
    │  A1 ────┼───────────┘                                │
    │         │                                            │
    │  A0 ────┼── (separate - resistance circuit)          │
    │         │                                            │
    └─────────┘                                            │
                                                           │
                           FAR END SHORT (K1+K2 LOW)       │
                           ┌───────────────────────────────┘
                           ▼ GND
```

## Pin Assignments

| Pin | Function | Description |
|-----|----------|-------------|
| D7  | CAP_CHARGE | Charges cable through 2.2MΩ resistor |
| D8  | CAP_DISCHARGE | Discharges cable through 1kΩ resistor |
| A1  | CAP_SENSE | Reads voltage on cable (dedicated for capacitance) |
| A0  | RES_SENSE | Resistance measurement (separate circuit) |
| D2  | K1_K2_RELAY | LOW = short far end for measurement |

## Component Values

| Component | Value | Purpose |
|-----------|-------|---------|
| R_charge | 2.2MΩ | Charging resistor - sets RC time constant |
| R_discharge | 1kΩ | Fast discharge between measurements |

## Expected Measurements

For typical audio cables:

| Cable Type | Capacitance | Charge Time (to 50%) |
|------------|-------------|----------------------|
| 10' low-cap (Canare GS-6) | ~150 pF | ~230 µs |
| 20' standard | ~600 pF | ~920 µs |
| 20' high-cap | ~1000 pF | ~1.5 ms |

Time constant: τ = R × C
For 50% threshold: t = τ × ln(2) = 0.693 × R × C

## Measurement Algorithm

1. **Discharge Phase**
   - Set D7 (charge) LOW
   - Set D8 (discharge) LOW (pulls to GND through 1kΩ)
   - Wait 10ms for complete discharge

2. **Charge Phase**
   - Set D8 to INPUT (high-impedance)
   - Set D7 HIGH (start charging through 2.2MΩ)
   - Start timer

3. **Detect Threshold**
   - Read A0 repeatedly
   - When ADC ≥ 512 (50% of 5V), stop timer
   - Record charge time in microseconds

4. **Calculate Capacitance**
   ```
   C = t / (R × ln(2))
   C = t / (2,200,000 × 0.693)
   C = t / 1,524,600
   ```
   Where t is in seconds, C is in Farads

## Calibration

Run CALCAP with test jacks shorted (no cable) to measure stray capacitance of the test fixture. This value is subtracted from all measurements.

Typical stray capacitance: 10-30 pF

## Relay Configuration for Capacitance Test

```
K1+K2 (D2): LOW  - Shorts far end of cable (sleeve to GND)
```

K4 (D14): LOW  - Capacitance mode (connects cap circuit to TIP)
                 HIGH - Resistance mode (connects resistance circuit to TIP)

## Parts List (Additional for Capacitance)

- 1x 2.2MΩ resistor (1% metal film preferred)
- 1x 1kΩ resistor (standard tolerance OK)
- Wiring: D7 and D8 to resistors, junction to test jack TIP via K4, A1 to same junction

## Integration Notes

The capacitance circuit uses dedicated pins:
- A1 for sensing (A0 is reserved for resistance)
- D7 for charging through 2.2MΩ
- D8 for discharging through 1kΩ

K1+K2 must be LOW to short the far end of the cable during measurement. The charging/sensing circuit connects to the TIP conductor at the near-end test jack.
