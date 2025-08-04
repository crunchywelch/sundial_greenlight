# Arduino Cable Tester Hardware Setup

## ATmega32 Pin Configuration

### Analog Inputs (A0-A5)
```
A0 - TIP Continuity Sense     (0-5V measurement)
A1 - RING Continuity Sense    (0-5V measurement)  
A2 - SLEEVE Continuity Sense  (0-5V measurement)
A3 - Resistance Measurement   (precision voltage measurement)
A4 - Capacitance Measurement  (RC timing measurement)
A5 - Supply Voltage Monitor   (reference voltage monitoring)
```

### Digital Outputs (D2-D13)
```
D2  - TEST_RELAY_TIP     (relay control for tip connection)
D3  - TEST_RELAY_RING    (relay control for ring connection)
D4  - TEST_RELAY_SLEEVE  (relay control for sleeve connection)
D5  - POLARITY_TEST_PIN  (test signal output, 0-5V)
D6  - RESISTANCE_CURRENT (precision current source enable)
D7  - CAPACITANCE_CHARGE (capacitance charging circuit enable)
D8  - CALIBRATION_RELAY  (calibration reference relay)
D9  - FIXTURE_DETECT     (INPUT with pullup - cable insertion detect)
D10 - FAIL_LED          (red LED - test failure indicator)
D11 - PASS_LED          (green LED - test pass indicator)  
D12 - ERROR_LED         (yellow LED - system error indicator)
D13 - STATUS_LED        (blue LED - system status/heartbeat)
```

### Serial Communication (D0-D1)
```
D0 - RX (USB serial receive)
D1 - TX (USB serial transmit)
```

## Test Circuit Design

### Continuity Testing Circuit
```
Arduino Pin → 1kΩ Resistor → Test Relay → Cable Connection
                ↓
         Analog Input ← Voltage Divider ← Cable Under Test
```

**Components needed:**
- 3x SPDT relays (5V coil) for tip/ring/sleeve switching
- 3x 1kΩ precision resistors for continuity testing
- 3x relay driver circuits (transistor + diode protection)

### Resistance Measurement Circuit
```
Precision Current Source (1mA) → Cable Under Test → Voltage Measurement
```

**Components needed:**
- Current source circuit (op-amp based, 1mA output)
- Precision voltage measurement (differential amplifier)
- Reference resistors for calibration

### Capacitance Measurement Circuit
```
5V → 10kΩ Resistor → Cable Capacitance → Ground
         ↓
   Arduino Analog Input (RC timing)
```

**Components needed:**
- 10kΩ precision resistor for RC timing
- Analog switch for discharge control
- Buffer amplifier for measurement

### Polarity Detection Circuit
```
Test Signal → Cable Tip
Ground ← Cable Sleeve
Measure voltage differential to determine polarity
```

## Required Components List

### Active Components
- 1x ATmega32 Arduino board
- 3x SPDT 5V relays (continuity switching)
- 1x SPDT 5V relay (calibration reference)
- 4x 2N2222 transistors (relay drivers)
- 4x 1N4001 diodes (relay protection)
- 1x LM358 op-amp (current source)
- 1x 74HC4066 analog switch (capacitance discharge)

### Passive Components
- 4x 1kΩ precision resistors (1% tolerance)
- 1x 10kΩ precision resistor (capacitance timing)
- 1x 100Ω precision resistor (current sense)
- 4x 10kΩ resistors (pull-ups)
- 4x 1kΩ resistors (LED current limiting)
- Various capacitors for decoupling

### Indicators
- 1x Red LED (fail indicator)
- 1x Green LED (pass indicator)  
- 1x Yellow LED (error indicator)
- 1x Blue LED (status/heartbeat)

### Connectors
- 1x USB connector (Arduino programming/communication)
- 2x 3.5mm TRS jacks (cable connection points)
- 1x Power connector (5V supply)

## Cable Test Fixture

### Mechanical Design
```
[Cable Jack A] ←→ [Test Circuit] ←→ [Cable Jack B]
       ↑                                    ↑
   Insertion                          Insertion
   Detection                          Detection
```

### Test Connections
- **TIP**: Audio signal conductor (usually center pin)
- **RING**: Secondary conductor (for balanced/stereo cables)
- **SLEEVE**: Ground/shield conductor (outer connector)

## Calibration Procedure

### 1. Voltage Reference Calibration
1. Connect precision voltage reference to calibration relay
2. Send `CALIBRATE` command to Arduino
3. Arduino measures reference and calculates calibration factor

### 2. Resistance Calibration
1. Connect short circuit between test points
2. Arduino measures "zero" resistance and records offset
3. Connect open circuit and verify high resistance reading

### 3. Capacitance Calibration  
1. Disconnect all test connections (open circuit)
2. Arduino measures stray capacitance and records offset
3. Connect known capacitor and verify accurate reading

## Communication Protocol

### Commands from Raspberry Pi
```
GET_UNIT_ID    → Returns unit identifier
GET_STATUS     → Returns system status
TEST_CABLE     → Runs complete cable test
CALIBRATE      → Runs calibration sequence
RESET          → Resets test circuit
SELF_TEST      → Runs power-on self test
```

### Responses to Raspberry Pi
```
UNIT_ID:1
STATUS:READY:FIXTURE_INSERTED:VOLTAGE_4.98
TEST_RESULT:CONTINUITY:1:RESISTANCE:0.245:CAPACITANCE:156.2:POLARITY:1:OVERALL:1
CALIBRATION:COMPLETE:VOLTAGE_CAL:1.0023:RESISTANCE_OFFSET:-0.012:CAPACITANCE_OFFSET:-2.3
ERROR:NO_CABLE_IN_FIXTURE
```

## Safety Considerations

### Electrical Safety
- All test voltages limited to 5V maximum
- Current limiting resistors on all outputs
- Relay isolation between test circuit and Arduino
- Fused power supply (1A fuse recommended)

### ESD Protection
- ESD protection diodes on all analog inputs
- Proper grounding of test fixture
- Anti-static work surface recommended

### Mechanical Safety
- Enclosed test fixture to prevent accidental contact
- Emergency stop capability
- Clear labeling of all connectors

## Installation Notes

### Power Requirements
- 5V @ 500mA minimum (for Arduino + relays)
- Clean, regulated power supply recommended
- Consider UPS for production environment

### Environmental
- Operating temperature: 10-40°C
- Humidity: <80% non-condensing  
- Dust protection recommended for production use

### Maintenance
- Monthly calibration verification
- Semi-annual relay contact cleaning
- Annual precision resistor verification