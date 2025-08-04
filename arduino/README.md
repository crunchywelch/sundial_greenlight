# Arduino Cable Tester

This directory contains the Arduino firmware for the Greenlight Cable Testing system.

## Files

### Main Firmware
- **`cable_tester.ino`** - Complete Arduino sketch for ATmega32
- **`CableTester.h`** - Arduino library header (for future modular development)

### Documentation  
- **`HARDWARE_SETUP.md`** - Detailed hardware requirements and circuit diagrams
- **`README.md`** - This file

## Quick Start

### 1. Hardware Setup
1. Connect ATmega32 Arduino to your computer via USB
2. Build test circuit according to `HARDWARE_SETUP.md` 
3. Connect cable test fixture to designated pins

### 2. Upload Firmware
1. Open `cable_tester.ino` in Arduino IDE
2. Select Board: "Arduino Uno" (or appropriate ATmega32 board)
3. Select correct COM port
4. Click Upload

### 3. Test Communication
1. Open Serial Monitor (9600 baud)
2. Send command: `GET_UNIT_ID`
3. Should receive: `UNIT_ID:1`
4. Send command: `GET_STATUS`
5. Should receive: `STATUS:READY:FIXTURE_EMPTY:VOLTAGE_X.XX`

## Supported Commands

| Command | Description | Response |
|---------|-------------|----------|
| `GET_UNIT_ID` | Get Arduino unit identifier | `UNIT_ID:1` |
| `GET_STATUS` | Get system status | `STATUS:READY:FIXTURE_EMPTY:VOLTAGE_4.98` |
| `TEST_CABLE` | Run complete cable test | `TEST_RESULT:CONTINUITY:1:RESISTANCE:0.245:CAPACITANCE:156.2:POLARITY:1:OVERALL:1` |
| `CALIBRATE` | Run calibration sequence | `CALIBRATION:COMPLETE:VOLTAGE_CAL:1.0023:...` |
| `RESET` | Reset test circuit | `RESET:COMPLETE` |
| `SELF_TEST` | Run power-on self test | `SELF_TEST:PASS:VOLTAGE:4.98` |

## Test Result Format

The Arduino returns test results in a structured format:

```
TEST_RESULT:CONTINUITY:1:RESISTANCE:0.245:CAPACITANCE:156.2:POLARITY:1:OVERALL:1
```

**Fields:**
- **CONTINUITY**: 1 = all connections good, 0 = open circuit detected
- **RESISTANCE**: DC resistance in ohms (e.g., 0.245Ω)  
- **CAPACITANCE**: Cable capacitance in picofarads (e.g., 156.2pF)
- **POLARITY**: 1 = correct, 0 = reversed
- **OVERALL**: 1 = pass, 0 = fail

## Hardware Requirements

### Minimum Components
- ATmega32 Arduino board
- 3x 5V SPDT relays (continuity switching)
- Basic test circuit (see HARDWARE_SETUP.md)
- 4x LEDs for status indication
- Cable test fixture with insertion detection

### Recommended Components  
- Precision current source for resistance measurement
- RC timing circuit for capacitance measurement
- Voltage reference for calibration
- ESD protection on all inputs

## Calibration

### Automatic Calibration
1. Send `CALIBRATE` command
2. Follow prompts for short circuit and open circuit connections
3. Calibration values are automatically calculated and stored

### Manual Calibration Values
You can adjust these constants in the code if needed:
```cpp
const float CONTINUITY_THRESHOLD_OHMS = 5.0;
const float VOLTAGE_REF = 5.0;
const float TEST_CURRENT_MA = 1.0;
```

## Troubleshooting

### No Response from Arduino
- Check USB connection and COM port
- Verify 9600 baud rate in Serial Monitor
- Check power LED on Arduino board

### Incorrect Test Results
- Run `SELF_TEST` command to verify hardware
- Check test fixture connections
- Run `CALIBRATE` to update calibration values
- Verify relay operation with multimeter

### Communication Errors
- Ensure clean 5V power supply
- Check for electrical noise interference  
- Verify all ground connections
- Consider USB isolation if needed

## Integration with Raspberry Pi

The Arduino communicates with the Raspberry Pi via USB serial. The Python code in the main project handles:

- Automatic Arduino detection on `/dev/ttyUSB*` ports
- Command/response protocol implementation
- Error handling and retries
- Integration with the Greenlight Terminal UI

## Development Notes

### Adding New Test Functions
1. Add command handling in `handleSerialCommand()`
2. Implement test function following existing patterns
3. Update response format documentation
4. Test with Python integration code

### Modifying Pin Assignments
1. Update pin definitions at top of `cable_tester.ino`
2. Update `HARDWARE_SETUP.md` documentation
3. Verify no pin conflicts with Arduino requirements

### Performance Optimization
- Adjust `MEASUREMENT_SAMPLES` for speed vs accuracy trade-off
- Modify delay times in test sequences as needed
- Consider interrupt-driven communication for faster response

## Production Deployment

### Quality Control
- Verify calibration accuracy with known standards
- Test all relay operations under load
- Validate measurement ranges with precision instruments
- Perform temperature stability testing

### Maintenance
- Monthly calibration verification
- Semi-annual precision component check  
- Annual full system validation
- Keep spare Arduino programmed and ready