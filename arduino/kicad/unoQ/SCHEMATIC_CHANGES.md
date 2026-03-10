# UNO Q Schematic Changes — Reference Guide

Mega 2560 schematic → UNO Q schematic.
Keep this open while editing in KiCad.

---

## PIN MAPPING (Mega → UNO Q)

| Signal               | Mega Pin | UNO Q Pin | Notes                        |
|----------------------|----------|-----------|------------------------------|
| TS_CONT_OUT_SLEEVE   | D2       | D2        | unchanged                    |
| TS_CONT_OUT_TIP      | D3       | D3        | unchanged                    |
| TS_CONT_IN_SLEEVE    | D4       | D4        | unchanged                    |
| TS_CONT_IN_TIP       | D5       | D5        | unchanged                    |
| RES_TEST_OUT         | D6       | D6        | unchanged                    |
| K1_K2_RELAY          | D14      | D7        | **add PN2222A driver**       |
| K3_RELAY             | D15      | D8        | **add PN2222A driver**       |
| K4_RELAY             | D16      | D9        | **add PN2222A driver**       |
| K5_RELAY             | D63      | D10       | **add PN2222A driver**       |
| K6_RELAY             | D62      | D11       | **add PN2222A driver**       |
| XLR_CONT_OUT_PIN1    | D69      | D12       |                              |
| XLR_CONT_OUT_PIN2    | D65      | D13       | shares LED_BUILTIN (cosmetic)|
| XLR_CONT_OUT_PIN3    | D64      | D15 (A1)  |                              |
| XLR_CONT_OUT_SHELL   | D61      | D16 (A2)  |                              |
| XLR_CONT_IN_PIN1     | D68      | D17 (A3)  |                              |
| XLR_CONT_IN_PIN2     | D67      | D18 (A4)  |                              |
| XLR_CONT_IN_PIN3     | D66      | D19 (A5)  |                              |
| XLR_CONT_IN_SHELL    | D60      | D20 (SDA) |                              |
| RES_SENSE            | A0       | A0        | **circuit now powered by 3.3V** |
| LED_FAIL (red)       | D19      | D53 (PH13)| onboard LED4 R + external via 220Ω |
| LED_PASS (green)     | D20      | D54 (PH14)| onboard LED4 G + external via 220Ω |
| LED_ERROR (blue)     | D21      | D55 (PH15)| onboard LED4 B + external via 220Ω |
| LED_STATUS (blue)    | —        | D52 (PH12)| onboard LED3 B + external via 220Ω |
| (spare)              | —        | D21 (SCL) | available if needed          |

---

## EXTERNAL STATUS LEDs

Keep D1 (RAGB LED), D2 (status LED), and their resistors R5-R8.
Rewire to onboard LED3/LED4 MCU pins (accent: same GPIO drives both
onboard SMD LED and external LED through enclosure).

| Ref  | Part      | MCU Pin    | Arduino Pin | Function           |
|------|-----------|------------|-------------|--------------------|
| D1-R | LED_RAGB  | PH13       | D53         | FAIL (red)         |
| D1-G | LED_RAGB  | PH14       | D54         | PASS (green)       |
| D1-B | LED_RAGB  | PH15       | D55         | ERROR (blue)       |
| D2   | LED       | PH12       | D52         | Status heartbeat   |
| R5   | 220Ω      | —          | —           | D1 red limiter     |
| R6   | 220Ω      | —          | —           | D1 green limiter   |
| R7   | 220Ω      | —          | —           | D1 blue limiter    |
| R8   | 220Ω      | —          | —           | D2 status limiter  |

Wire external LEDs from LED4/LED3 pads through R5-R8 to enclosure.
Board mounts inverted — LED4 (result) on top, LED3 (status) below.
Onboard LEDs light in parallel for bench testing visibility.
Status LED (D52) blinks at 1Hz heartbeat when system is ready.

---

## COMPONENTS TO ADD — RELAY DRIVERS (x5)

Each relay control line gets an identical NPN low-side switch:

```
                +5V
                 │
            relay coil A2
                 │
                 K (coil)
                 │
            relay coil A1
                 │
                 C (collector)
                 │
    GPIO ──[1kΩ]──B  PN2222A
                 │
                 E (emitter)
                 │
                GND
```

Wiring detail:
- GPIO pin → 1kΩ resistor → PN2222A base (pin 2)
- PN2222A emitter (pin 1) → GND
- PN2222A collector (pin 3) → relay coil pin A1
- Relay coil pin A2 → +5V
- Flyback diode across coil (cathode to +5V, anode to A1) — already exists

The transistor sinks relay current to ground (low-side switch).
Relay sees ~4.8V (5V minus Vce(sat) ≈ 0.2V).
Base drive: (3.3V - 0.7V) / 1kΩ = 2.6mA — sufficient to saturate for relay coil current.

### New parts list

| Ref   | Value   | Drives      | GPIO |
|-------|---------|-------------|------|
| Q2    | PN2222A | K1+K2 coil  | D7   |
| Q3    | PN2222A | K3 coil     | D8   |
| Q4    | PN2222A | K4 coil     | D9   |
| Q5    | PN2222A | K5 coil     | D10  |
| Q6    | PN2222A | K6 coil     | D11  |
| R14   | 1kΩ     | Q2 base     |      |
| R15   | 1kΩ     | Q3 base     |      |
| R16   | 1kΩ     | Q4 base     |      |
| R17   | 1kΩ     | Q5 base     |      |
| R18   | 1kΩ     | Q6 base     |      |

---

## RESISTANCE CIRCUIT CHANGE

The ONLY change to the existing resistance circuit:

- **R2 (20Ω) high side: reconnect from +5V to +3.3V**
- Q1, R1 (330Ω base), A0 sense — all stay the same
- Flyback diode stays

Reason: A0 on UNO Q is NOT 5V tolerant. Running from 3.3V keeps
A0 voltage within safe range. Calibration compensates automatically.

Base drive note: D6 at 3.3V through R1 (330Ω) gives
Ib = (3.3 - 0.7) / 330 = 7.9mA — sufficient for the test current.

---

## ARDUINO HEADERS

Replace Mega headers (J1, J3, J6, J11) with UNO Q header layout.

UNO Q header pins (from pinout diagram):

**Right side (top to bottom):**
D21(SCL), D20(SDA), AREF, GND,
D13, D12, D11, D10, D9, D8,
D7, D6, D5, D4, D3, D2, D1(TX), D0(RX)

**Left side (bottom to top):**
A0, A1, A2, A3, A4, A5

**Power header:**
+5V, +3.3V, GND, VIN, IOREF, RESET

---

## EXISTING COMPONENTS — NO CHANGES

| Ref     | Part      | Notes                              |
|---------|-----------|------------------------------------|
| K1–K6   | G6K-2P-5V | Keep all 6 relays and contacts    |
| Q1      | PN2222A   | Resistance test transistor (keep) |
| R1      | 330Ω      | Q1 base resistor (keep)           |
| R2      | 20Ω       | R_sense (keep, rewire to 3.3V)    |
| R3,R4   | 10K       | Pulldowns (keep)                   |
| R5–R8   | 220Ω      | LED current limiters (keep, rewire)|
| R9,R10  | 10K       | Pulldowns (keep)                   |
| R13     | 10K       | Pulldown (keep)                    |
| D1      | LED_RAGB  | Pass/fail/error LED (keep, rewire)|
| D2      | LED       | Status heartbeat LED (keep, rewire)|
| D3,D5,D6| 1N4007    | Flyback diodes (keep)             |
| D8,D9   | 1N4007    | Flyback diodes (keep)             |
| D12     | 1N4007    | Flyback diode (keep)              |
| J2      | AudioJack2| TS test jack (keep)               |
| J4,J5   | XLR3      | XLR test jacks (keep)             |

---

## CHECKLIST

- [ ] Rewire D1 (RAGB) + R5/R6/R7 to LED3 pads (D50/D51/D52)
- [ ] Rewire D2 (status) + R8 to LED4 Blue pad (D55)
- [ ] Remove old D19/D20/D21 net labels (Mega LED pins)
- [ ] Add Q2-Q6 (PN2222A) with R14-R18 (1kΩ) for relay drives
- [ ] Wire each relay coil through its new transistor driver
- [ ] Rewire R2 high side from +5V to +3.3V
- [ ] Update all Arduino header connectors for UNO Q pinout
- [ ] Rename all net labels per pin mapping table above
- [ ] Verify all flyback diodes still connect across relay coils
