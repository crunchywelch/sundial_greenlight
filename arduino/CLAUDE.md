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
XSHELL   → XSHELL:PASS:NEAR:1:FAR:1:SS:1
XRES     → XRES:PASS:P2ADC:150:P3ADC:148:...
XCAL     → XCAL:OK:P2ADC:120:P3ADC:118
```

## Pin Configuration (UNO Q)

See full pinout in sketch header. Key assignments:
- **D2-D5:** TS continuity (drive/sense for tip and sleeve)
- **D6:** Resistance test drive (shared TS/XLR via PN2222A)
- **D7-D11:** Relay drives K1-K6 (via PN2222A transistors, coils on 5V)
- **D12-D13, A1-A5, D20:** XLR continuity (drive/sense for pins 1-3 + shell)
- **A0:** Resistance sense (analog, 3.3V circuit only)

## LED Matrix

The UNO Q has an onboard 8x13 LED matrix with 8-level grayscale:
- `matrix.begin()` / `matrix.draw(uint8_t[104])` / `matrix.setGrayscaleBits(3)`
- Idle: scrolls "Sundial Wire" with edge fade effect
- Tests: shows checkmark (pass), X (fail), or ! (error) for 3 seconds
- Font: built-in 5x7 column-major (A-Z, a-z), `FONT_5x7[]` array in sketch