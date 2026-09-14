# Hardware Setup — Arduino UNO Q

## Overview

- **MCU:** STM32U5 (Cortex-M33), 3.3V GPIO, 14-bit ADC (0–16383)
- **Communication:** Router Bridge (msgpack-rpc over unix socket)
- **Relay drive:** Via PN2222A NPN transistors (3.3V GPIO can't drive 5V coils directly)
- **Display:** Onboard 8×13 LED matrix (grayscale, zero GPIO cost)
- **Sketch:** `ArduinoApps/cable-tester/sketch/sketch.ino`

## Pin Configuration

### Relay Drives (via PN2222A transistors)

Each relay line: GPIO → 1kΩ → PN2222A base. Collector to relay coil A1, emitter to GND, coil A2 to +5V.

| Pin | Signal    | Transistor | Drives | Function                                           |
|-----|-----------|------------|--------|----------------------------------------------------|
| D2  | K1_K2     | Q2         | K1+K2  | TS test mode: LOW = short far end + res, HIGH = continuity |
| D3  | K3        | Q3         | K3     | Resistance circuit: LOW = TS, HIGH = XLR           |
| D4  | K4        | Q4         | K4     | XLR res pin select: LOW = Pin 2, HIGH = Pin 3     |
| D10 | K5        | Q5         | K5     | XLR Pin 2: LOW = continuity, HIGH = resistance    |
| D11 | K6        | Q6         | K6     | XLR Pin 3: LOW = continuity, HIGH = resistance    |

### TS Cable Testing

| Pin | Signal             | Direction | Function                        |
|-----|--------------------|-----------|---------------------------------|
| D5  | TS_CONT_OUT_SLEEVE | OUTPUT    | Continuity drive, sleeve        |
| D6  | TS_CONT_OUT_TIP    | OUTPUT    | Continuity drive, tip           |
| D7  | TS_CONT_IN_SLEEVE  | INPUT     | Continuity sense, sleeve        |
| D8  | TS_CONT_IN_TIP     | INPUT     | Continuity sense, tip           |

### Resistance

| Pin     | Signal       | Direction | Function                                           |
|---------|--------------|-----------|-----------------------------------------------------|
| D9      | RES_TEST_OUT | OUTPUT    | PN2222A base drive via 330Ω (shared TS/XLR)         |
| A0 (D14)| RES_SENSE    | ANALOG IN | High-side sense resistor junction (**3.3V circuit**) |

**A0 is NOT 5V tolerant** — resistance circuit must be powered from 3.3V rail.

### XLR Cable Testing

| Pin        | Signal             | Direction | Function                        |
|------------|--------------------|-----------|---------------------------------|
| D12        | XLR_CONT_OUT_PIN1  | OUTPUT    | Continuity drive, pin 1         |
| A5 (D19)   | XLR_CONT_IN_PIN1   | INPUT     | Continuity sense, pin 1         |
| A2 (D16)   | XLR_CONT_OUT_PIN2  | OUTPUT    | Continuity drive, pin 2 (K5)    |
| A3 (D17)   | XLR_CONT_IN_PIN2   | INPUT     | Continuity sense, pin 2 (K5)    |
| A1 (D15)   | XLR_CONT_OUT_PIN3  | OUTPUT    | Continuity drive, pin 3 (K6)    |
| A4 (D18)   | XLR_CONT_IN_PIN3   | INPUT     | Continuity sense, pin 3 (K6)    |
| D21 (SCL)  | XLR_CONT_OUT_SHELL | OUTPUT    | Continuity drive, shell (near)  |
| D20 (SDA)  | XLR_CONT_IN_SHELL  | INPUT     | Continuity sense, shell (far)   |

### Status LED

| Pin | Signal     | Function                         |
|-----|------------|----------------------------------|
| D13 | STATUS_LED | Built-in LED, heartbeat          |

## UNO Q Header Pinout (for breadboard reference)

**Right side (top to bottom):**
```
D21(SCL), D20(SDA), AREF, GND,
D13, D12, D11, D10, D9, D8,
D7, D6, D5, D4, D3, D2, D1(TX), D0(RX)
```

**Left side (bottom to top):**
```
A0, A1, A2, A3, A4, A5
```

**Power header:**
```
+5V, +3.3V, GND, VIN, IOREF, RESET
```

## Resistance Measurement Circuit

High-side sense topology with **3.3V** supply (changed from Mega's 5V):

```
+3.3V → R_sense (20Ω) → cable → relay → PN2222A collector
                   ↓                          ↓
                  A0 (sense)             emitter → GND
```

- D9 drives Q1 (PN2222A) base through R1 (330Ω)
- Base drive: (3.3V − 0.7V) / 330Ω = 7.9mA — sufficient to saturate
- A0 reads voltage at junction of R_sense and cable
- 14-bit ADC gives much finer resolution than Mega's 10-bit
- Calibration (`CAL` command) compensates for 3.3V supply automatically

## Relay Driver Circuit (×5)

NPN low-side switch — identical for all five drivers (Q2–Q6):

```
              +5V
               │
          relay coil A2
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

- Base drive: (3.3V − 0.7V) / 1kΩ = 2.6mA — sufficient to saturate
- Relay sees ~4.8V (5V minus Vce(sat) ≈ 0.2V)
- Flyback diode across each coil (cathode to +5V, anode to A1) — already on PCB

## Relay Configuration

Six G6K-2P-5V DPDT relays (K1–K6), all with 1N4007 flyback diodes across coils.

| Relay | Function                                                    |
|-------|-------------------------------------------------------------|
| K1+K2 | Tied together. TS test mode switching                      |
| K3    | Resistance circuit: routes to TS or XLR path               |
| K4    | XLR resistance pin select: Pin 2 or Pin 3                  |
| K5    | XLR Pin 2 mode: continuity or resistance                   |
| K6    | XLR Pin 3 mode: continuity or resistance                   |

## Components

### Active

| Ref    | Part      | Function                                   |
|--------|-----------|--------------------------------------------|
| Q1     | PN2222A   | Resistance test transistor (existing)      |
| Q2–Q6  | PN2222A   | Relay drivers (new for UNO Q)              |
| K1–K6  | G6K-2P-5V | Test switching relays                      |

### Passive

| Ref      | Value | Function                          |
|----------|-------|-----------------------------------|
| R1       | 330Ω  | Q1 base resistor                  |
| R2       | 20Ω   | Resistance sense (**to +3.3V**)   |
| R3,R4    | 10K   | Pulldowns                         |
| R5       | 220Ω  | Fail LED limiter                  |
| R6       | 220Ω  | Pass LED limiter                  |
| R7       | 220Ω  | Error LED limiter                 |
| R8       | 220Ω  | Status LED limiter                |
| R9,R10   | 10K   | Pulldowns                         |
| R13      | 10K   | Pulldown                          |
| R14–R18  | 1kΩ   | Relay driver base resistors (new) |

### Diodes

| Ref                  | Part   | Function            |
|----------------------|--------|---------------------|
| D3,D5,D6,D8,D9,D12  | 1N4007 | Relay flyback diodes |

### Connectors

| Ref | Part       | Function         |
|-----|------------|------------------|
| J2  | AudioJack2 | TS test jack     |
| J4  | XLR3       | XLR test jack A  |
| J5  | XLR3       | XLR test jack B  |

### Indicators

| Ref | Part     | Function                              |
|-----|----------|---------------------------------------|
| D1  | LED_RAGB | Pass/fail/error (RGB, external + LED4)|
| D2  | LED      | Status heartbeat (external + LED3)    |

## Communication Protocol

See `arduino/CLAUDE.md` for full command/response reference. Key commands:

```
ID       → ID:UNOQ_TESTER_1
STATUS   → STATUS:READY
CONT     → RESULT:PASS:TT:1:TS:0:SS:1:ST:0
RES      → RES:PASS:ADC:150:CAL:120:MOHM:450:OHM:0.450
CAL      → CAL:OK:ADC:120
XCONT    → XCONT:PASS:P11:1:P12:0:...
XSHELL   → XSHELL:PASS:NEAR:1:FAR:1:SS:1
XRES     → XRES:PASS:P2ADC:150:P3ADC:148:...
XCAL     → XCAL:OK:P2ADC:120:P3ADC:118
RESET    → OK:RESET
```
