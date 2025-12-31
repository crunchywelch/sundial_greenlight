# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Environment

This is an Arduino project for cable testing hardware integration with the Greenlight Terminal system. The Arduino code communicates with a Raspberry Pi via USB serial.

### Build and Upload Commands

```bash
# Using arduino-cli (Recommended for Raspberry Pi)
# Compile the sketch
arduino-cli compile --fqbn arduino:avr:mega cable_tester

# Upload to Arduino Mega 2560 (via built-in USB)
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester

# Monitor serial output (9600 baud)
arduino-cli monitor -p /dev/ttyACM0 -c baudrate=9600

# One-liner: compile and upload
cd arduino && arduino-cli compile --fqbn arduino:avr:mega cable_tester && arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester

# Alternative: Using Arduino IDE
# 1. Open cable_tester/cable_tester.ino in Arduino IDE
# 2. Select Board: Tools > Board > Arduino AVR Boards > Arduino Mega or Mega 2560
# 3. Select correct COM port: Tools > Port > /dev/ttyACM0
# 4. Click Upload button
```

**Board Specifications:**
- **Board:** Arduino Mega 2560 R3
- **Processor:** ATmega2560
- **FQBN:** `arduino:avr:mega`
- **Built-in USB:** No external USB-to-serial adapter needed
- **Serial Port:** Usually `/dev/ttyACM0` on Linux

**Memory Usage:**
- Program storage: 12,404 bytes (4% of 253,952 bytes) ✅
- Dynamic memory: 1,744 bytes (21% of 8,192 bytes) ✅
- Free RAM: 6,448 bytes for local variables - excellent headroom!

### Testing and Communication

```bash
# Test serial communication (9600 baud)
screen /dev/ttyUSB0 9600
# Or using minicom
minicom -b 9600 -D /dev/ttyUSB0

# Basic test commands:
# GET_UNIT_ID → Should return: UNIT_ID:1
# GET_STATUS → Should return: STATUS:READY:FIXTURE_EMPTY:VOLTAGE_X.XX
# TEST_CABLE → Runs complete cable test
```

## Architecture Overview

**Arduino Cable Tester** is the hardware interface component of the Greenlight audio cable testing system. It provides precision measurement capabilities via an ATmega32 Arduino board.

### Core Components

- **cable_tester.ino**: Complete Arduino sketch with all testing functionality
- **CableTester.h**: Library header for modular development (future use)
- **HARDWARE_SETUP.md**: Detailed hardware requirements and circuit diagrams

### Hardware Interface Design

The Arduino controls a precision test circuit using:
- **3x SPDT relays**: Continuity testing for tip/ring/sleeve connections
- **Precision measurement circuits**: DC resistance and capacitance measurement
- **LED indicators**: Pass/fail/error/status indication
- **Cable fixture**: Physical cable insertion detection

### Communication Protocol

Arduino communicates with Raspberry Pi via USB serial (9600 baud) using structured commands:

```
Commands: GET_UNIT_ID, GET_STATUS, TEST_CABLE, CALIBRATE, RESET, SELF_TEST
Responses: UNIT_ID:1, STATUS:READY:FIXTURE_EMPTY:VOLTAGE_4.98, TEST_RESULT:...
```

### Test Capabilities

1. **Continuity Testing**: Verifies tip, ring, and sleeve connections
2. **Polarity Detection**: Ensures correct conductor polarity  
3. **DC Resistance Measurement**: Precision resistance via constant current
4. **Capacitance Measurement**: Cable capacitance via RC timing method
5. **Self-Calibration**: Automated calibration with user prompts

### Pin Configuration (ATmega32)

- **A0-A5**: Analog inputs for voltage measurements
- **D2-D8**: Relay and test circuit control
- **D9**: Cable insertion detection (INPUT_PULLUP)
- **D10-D13**: LED indicators (fail/pass/error/status)
- **D0-D1**: USB serial communication

## Integration Notes

### Raspberry Pi Integration

The Arduino is designed to integrate with the main Greenlight Terminal system:
- Automatic detection on `/dev/ttyUSB*` ports
- Python code handles command/response protocol
- Error handling and retry logic
- Integration with Rich terminal UI

### Calibration Requirements

The system requires calibration for accurate measurements:
- **Voltage reference calibration**: Using precision reference
- **Resistance offset calibration**: Short circuit zeroing
- **Capacitance offset calibration**: Open circuit baseline

### Hardware Dependencies

- ATmega32 Arduino board with USB serial
- Custom test circuit (see HARDWARE_SETUP.md)
- 5V power supply (500mA minimum)
- Cable test fixture with insertion detection

## Development Notes

### Code Structure

The Arduino sketch uses a command-response architecture:
- **setup()**: Pin initialization and power-on self-test
- **loop()**: Serial command handling and status heartbeat  
- **handleSerialCommand()**: Command parser and dispatcher
- **Test functions**: Modular measurement implementations

### Adding New Test Functions

1. Add command handling in `handleSerialCommand()`
2. Implement test function following existing patterns
3. Update response format in `sendTestResults()`
4. Test integration with Python communication code

### Measurement Accuracy

Key calibration constants that may need adjustment:
```cpp
const float CONTINUITY_THRESHOLD_OHMS = 5.0;
const float VOLTAGE_REF = 5.0; 
const int MEASUREMENT_SAMPLES = 50;
```

### Hardware Modifications

When modifying pin assignments:
1. Update pin definitions at top of `cable_tester.ino`
2. Update `HARDWARE_SETUP.md` documentation  
3. Verify no conflicts with Arduino system requirements
4. Test all relay and measurement functions

The system is designed for production cable testing environments and emphasizes measurement accuracy, reliability, and integration with the broader Greenlight Terminal ecosystem.