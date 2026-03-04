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
| (spare)              | —        | D21 (SCL) | available if needed          |

---

## COMPONENTS TO REMOVE

| Ref  | Part      | Why                              |
|------|-----------|----------------------------------|
| D1   | LED_RAGB  | Using onboard RGB LEDs instead   |
| D2   | LED       | Status LED not needed externally |
| R5   | 220Ω      | D1 red current limiter           |
| R6   | 220Ω      | D1 green current limiter         |
| R7   | 220Ω      | D1 blue current limiter          |
| R8   | 220Ω      | D2 current limiter               |

Remove net labels D19, D20, D21 (were FAIL/PASS/ERROR LEDs, no longer used).

**Display uses onboard 8x13 LED matrix** (PE0-7 rows, PG0-12 cols).
Driven internally by MCU — no external components, no GPIO cost.
Controlled via `Arduino_LED_Matrix` library (same API as UNO R4 WiFi).
Shows checkmark (pass), X (fail), ! (error), dot (idle heartbeat).

---

## COMPONENTS TO ADD — RELAY DRIVERS (x5)

Each relay control line gets an identical sub-circuit:

```
                      +5V
                       │
                  ┌────┤ A2
                  │    │
    GPIO ──[1kΩ]──┤B   K (relay coil)
                  │    │
                  │Q   ├ A1
                  │    │
              PN2222A  │C
                  │    │
                  │E   │
                  │    │
                 GND  GND
```

Wiring detail:
- GPIO pin → 1kΩ resistor → PN2222A base (pin 2)
- PN2222A emitter (pin 1) → GND
- PN2222A collector (pin 3) → relay coil pin A1
- Relay coil pin A2 → +5V
- Flyback diode across coil (cathode to +5V, anode to A1) — already exists

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
| R9,R10  | 10K       | Pulldowns (keep)                   |
| R13     | 10K       | Pulldown (keep)                    |
| D3,D5,D6| 1N4007    | Flyback diodes (keep)             |
| D8,D9   | 1N4007    | Flyback diodes (keep)             |
| D12     | 1N4007    | Flyback diode (keep)              |
| J2      | AudioJack2| TS test jack (keep)               |
| J4,J5   | XLR3      | XLR test jacks (keep)             |

---

## CHECKLIST

- [ ] Remove D1, D2, R5, R6, R7, R8
- [ ] Remove D19/D20/D21 net labels (LED pins)
- [ ] Add Q2-Q6 (PN2222A) with R14-R18 (1kΩ) for relay drives
- [ ] Wire each relay coil through its new transistor driver
- [ ] Rewire R2 high side from +5V to +3.3V
- [ ] Update all Arduino header connectors for UNO Q pinout
- [ ] Rename all net labels per pin mapping table above
- [ ] Verify all flyback diodes still connect across relay coils
