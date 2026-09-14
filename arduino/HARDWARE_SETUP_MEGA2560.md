# Hardware Setup — Arduino Mega 2560

## Overview

- **MCU:** ATmega2560, 5V GPIO, 10-bit ADC (0–1023)
- **Communication:** USB serial at 9600 baud (`/dev/ttyACM0`)
- **Relay drive:** Direct GPIO (5V outputs can sink/source relay coils directly)
- **Sketch:** `arduino/cable_tester/cable_tester.ino`

## Pin Configuration

### TS Cable Testing

| Pin | Signal             | Direction | Function                        |
|-----|--------------------|-----------|---------------------------------|
| D2  | TS_CONT_OUT_SLEEVE | OUTPUT    | Continuity drive, sleeve        |
| D3  | TS_CONT_OUT_TIP    | OUTPUT    | Continuity drive, tip           |
| D4  | TS_CONT_IN_SLEEVE  | INPUT     | Continuity sense, sleeve        |
| D5  | TS_CONT_IN_TIP     | INPUT     | Continuity sense, tip           |

### Resistance

| Pin | Signal       | Direction | Function                                          |
|-----|--------------|-----------|---------------------------------------------------|
| D6  | RES_TEST_OUT | OUTPUT    | PN2222A base drive via 330Ω (shared TS/XLR)       |
| A0  | RES_SENSE    | ANALOG IN | High-side sense resistor junction (0–5V safe)     |

### Relay Drives (direct GPIO)

| Pin | Signal    | Drives    | Function                                           |
|-----|-----------|-----------|----------------------------------------------------|
| D14 | K1_K2     | K1+K2     | TS test mode: LOW = short far end + res, HIGH = continuity |
| D15 | K3        | K3        | Resistance circuit: LOW = TS, HIGH = XLR           |
| D16 | K4        | K4        | XLR res pin select: LOW = Pin 2, HIGH = Pin 3     |
| D63 | K5        | K5        | XLR Pin 2: LOW = continuity, HIGH = resistance    |
| D62 | K6        | K6        | XLR Pin 3: LOW = continuity, HIGH = resistance    |

### XLR Cable Testing

| Pin | Signal             | Direction | Function                        |
|-----|--------------------|-----------|---------------------------------|
| D69 | XLR_CONT_OUT_PIN1  | OUTPUT    | Continuity drive, pin 1         |
| D68 | XLR_CONT_IN_PIN1   | INPUT     | Continuity sense, pin 1         |
| D65 | XLR_CONT_OUT_PIN2  | OUTPUT    | Continuity drive, pin 2 (K5)    |
| D67 | XLR_CONT_IN_PIN2   | INPUT     | Continuity sense, pin 2 (K5)    |
| D64 | XLR_CONT_OUT_PIN3  | OUTPUT    | Continuity drive, pin 3 (K6)    |
| D66 | XLR_CONT_IN_PIN3   | INPUT     | Continuity sense, pin 3 (K6)    |
| D61 | XLR_CONT_OUT_SHELL | OUTPUT    | Continuity drive, shell (near)  |
| D60 | XLR_CONT_IN_SHELL  | INPUT     | Continuity sense, shell (far)   |

### LEDs

| Pin | Signal     | Function          |
|-----|------------|-------------------|
| D13 | STATUS_LED | Built-in, heartbeat |
| D19 | FAIL_LED   | Red               |
| D20 | PASS_LED   | Green             |
| D21 | ERROR_LED  | Blue              |

### Serial

| Pin | Function |
|-----|----------|
| D0  | RX       |
| D1  | TX       |

## Resistance Measurement Circuit

High-side sense topology with 5V supply:

```
+5V → R_sense (20Ω) → cable → relay → PN2222A collector
                  ↓                         ↓
                 A0 (sense)            emitter → GND
```

- D6 drives PN2222A base through 330Ω resistor
- A0 reads voltage at junction of R_sense and cable
- Lower ADC = more current = lower cable resistance
- Pass threshold: ~1Ω max cable resistance
- `CAL` command with short cable records ADC baseline

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

| Ref   | Part      | Function                    |
|-------|-----------|-----------------------------|
| Q1    | PN2222A   | Resistance test transistor  |
| K1–K6 | G6K-2P-5V | Test switching relays       |

### Passive

| Ref    | Value | Function                  |
|--------|-------|---------------------------|
| R1     | 330Ω  | Q1 base resistor          |
| R2     | 20Ω   | Resistance sense (to +5V) |
| R3,R4  | 10K   | Pulldowns                 |
| R5     | 220Ω  | Fail LED limiter          |
| R6     | 220Ω  | Pass LED limiter          |
| R7     | 220Ω  | Error LED limiter         |
| R8     | 220Ω  | Status LED limiter        |
| R9,R10 | 10K   | Pulldowns                 |
| R13    | 10K   | Pulldown                  |

### Diodes

| Ref              | Part   | Function           |
|------------------|--------|--------------------|
| D3,D5,D6,D8,D9,D12 | 1N4007 | Relay flyback diodes |

### Connectors

| Ref  | Part       | Function         |
|------|------------|------------------|
| J2   | AudioJack2 | TS test jack     |
| J4   | XLR3       | XLR test jack A  |
| J5   | XLR3       | XLR test jack B  |

### Indicators

| Ref | Part     | Function              |
|-----|----------|-----------------------|
| D1  | LED_RAGB | Pass/fail/error (RGB) |
| D2  | LED      | Status heartbeat      |

## Communication Protocol

See `arduino/CLAUDE.md` for full command/response reference. Key commands:

```
ID       → ID:TS_TESTER_1
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
