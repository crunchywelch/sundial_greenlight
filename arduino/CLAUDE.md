# CLAUDE.md

This file provides guidance to Claude Code when working with Arduino hardware code.

## Dual-Platform Architecture

The cable tester runs on two platforms. Both use the same colon-delimited text command protocol.

### Arduino UNO Q (primary)
- **MCU:** STM32U5 (Cortex-M33), 3.3V GPIO, 14-bit ADC
- **Sketch:** `ArduinoApps/cable-tester/sketch/sketch.ino`
- **Communication:** Router Bridge (msgpack-rpc over unix socket `/var/run/arduino-router.sock`)
- **Platform core:** `arduino:zephyr` v0.53.1
- **Display:** Onboard 8x13 LED matrix (grayscale, zero GPIO cost)
- **Flash:** ~29KB / 1.9MB (1.5%), RAM: ~4.8KB / 523KB (0.9%)

### Arduino Mega 2560 (legacy)
- **MCU:** ATmega2560, 5V GPIO, 10-bit ADC
- **Sketch:** `arduino/cable_tester/cable_tester.ino`
- **Communication:** USB serial at 9600 baud (`/dev/ttyACM0`)
- **FQBN:** `arduino:avr:mega`

## Build and Deploy

```bash
# Auto-detects platform (UNO Q or Mega 2560), compiles and flashes
cd arduino && ./deploy.sh

# UNO Q only: also set as boot default app
cd arduino && ./deploy.sh --set-default

# Interactive command monitor (auto-detects platform)
cd arduino && ./monitor.sh
```

### UNO Q Deploy Details

The UNO Q uses Arduino App Studio's framework:
- Apps live in `ArduinoApps/<app-name>/` (symlinked to `/home/arduino/ArduinoApps/`)
- CLI tool: `sudo -u arduino arduino-app-cli` (must NOT run as root)
- Deploy = `app stop` + `app start` (compiles, flashes via OpenOCD/SWD)
- Boot default stored in `/var/lib/arduino-app-cli/default.app` (path to app dir)
- The App Studio UI sets this automatically; from CLI: `echo "/path/to/app" | sudo tee /var/lib/arduino-app-cli/default.app`
- MCU sketch persists in flash but Bridge RPC registration requires the `arduino-app-cli` daemon to start the app

### UNO Q Key Commands

```bash
sudo -u arduino arduino-app-cli app list          # list apps and status
sudo -u arduino arduino-app-cli app start user:cable-tester
sudo -u arduino arduino-app-cli app stop user:cable-tester
sudo -u arduino arduino-app-cli app logs user:cable-tester
```

## Command Protocol

Both platforms accept identical text commands and return colon-delimited responses:

```
ID       → ID:UNOQ_TESTER_1
STATUS   → STATUS:READY
RESET    → OK:RESET
CONT     → RESULT:PASS:TT:1:TS:0:SS:1:ST:0  (or FAIL with :REASON:...)
RES      → RES:PASS:ADC:150:CAL:120:MOHM:450:OHM:0.450
CAL      → CAL:OK:ADC:120
XCONT    → XCONT:PASS:P11:1:P12:0:P13:0:P21:0:P22:1:P23:0:P31:0:P32:0:P33:1
XSHELL   → XSHELL:PASS:NEAR:1:FAR:1:SS:1   (Mega only; UNO Q → ERROR:NOT_SUPPORTED:XSHELL)
XRES     → XRES:PASS:P2ADC:150:P3ADC:148:...
XCAL     → XCAL:OK:P2ADC:120:P3ADC:118
```

## Pin Configuration (UNO Q)

The schematic `kicad/unoQ/greenlight-tester-unoQ.kicad_sch` matches the built
board and is the source of truth; the full table lives in the sketch header.
Assignments follow the stacked proto boards (limited through-holes, partly
soldered), so they aren't grouped logically. `kicad/unoQ/SCHEMATIC_CHANGES.md`
is the original Mega→UNO Q migration plan and its pin table is stale.

- **D2:** Status LED · **D20/D21:** result LED red/green (D6 LED_RAGB)
- **D3 / D5 / D12 / D10 / D11:** relay drivers K1+K2 / K3 / K4 / K5 / K6 (PN2222A, coils on 5V)
- **D6/D7 → D8/D9:** TS continuity drive → sense (sleeve/tip)
- **D13:** resistance test drive (Q3); **A0:** resistance sense (R8 20Ω from +3V3)
- **XLR (J4 drive end → J3 sense end):** pin 1 D4→A5, pin 2 A2→A4 (K5), pin 3 A1→A3 (K6)
- **XLR shell test:** no pins left on UNO Q; XSHELL is unsupported

## LED Matrix

The UNO Q has an onboard 8x13 LED matrix with 8-level grayscale:
- `matrix.begin()` / `matrix.draw(uint8_t[104])` / `matrix.setGrayscaleBits(3)`
- Idle: scrolls "Sundial Wire" with edge fade effect
- Tests: shows checkmark (pass), X (fail), or ! (error) for 3 seconds
- Font: built-in 5x7 column-major (A-Z, a-z), `FONT_5x7[]` array in sketch