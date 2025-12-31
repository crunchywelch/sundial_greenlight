# Arduino Mega 2560 - Quick Start Guide

## Hardware Setup
- **Board:** Arduino Mega 2560 R3
- **Connection:** USB cable from Raspberry Pi to Arduino
- **Serial Port:** `/dev/ttyACM0` (usually)
- **Power:** USB provides power (no external supply needed)

## Compilation & Upload

### One-Line Deploy
```bash
cd arduino && arduino-cli compile --fqbn arduino:avr:mega cable_tester && arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester
```

### Step by Step
```bash
# 1. Compile
arduino-cli compile --fqbn arduino:avr:mega cable_tester

# 2. Upload
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester

# 3. Monitor
arduino-cli monitor -p /dev/ttyACM0 -c baudrate=9600
```

## Test Commands

Once uploaded, test communication by sending these commands:

```
GET_UNIT_ID       → Returns: UNIT_ID:1
GET_STATUS        → Returns: STATUS:READY:...
TEST_CABLE        → Runs full cable test
SELF_TEST         → Runs power-on self test
```

## Memory Usage (Excellent!)

```
✅ Flash: 12,404 / 253,952 bytes (4% used)
✅ RAM:   1,744 / 8,192 bytes (21% used)
✅ Free:  6,448 bytes for local variables
```

## Troubleshooting

### Find Serial Port
```bash
arduino-cli board list
# or
ls -l /dev/ttyACM* /dev/ttyUSB*
```

### Permission Error
```bash
sudo usermod -a -G dialout $USER
# Then log out and back in
```

### Upload Fails
- Try different USB cable
- Press RESET button on Arduino
- Verify port: `arduino-cli board list`
- Check USB connection: `lsusb | grep Arduino`

## Python Integration

Enable real Arduino in `greenlight/config.py`:
```python
USE_REAL_ARDUINO = True
ARDUINO_PORT = "/dev/ttyACM0"  # or None for auto-detect
ARDUINO_BAUDRATE = 9600
```

## Why Mega 2560?

| Feature | Pro Mini | **Mega 2560** |
|---------|----------|---------------|
| Flash | 30KB (36% used) | **253KB (4% used)** ✅ |
| RAM | 2KB (85% used) | **8KB (21% used)** ✅ |
| USB | External adapter | **Built-in** ✅ |
| Pins | 14 digital, 6 analog | **54 digital, 16 analog** ✅ |

**Result:** Much better stability and room for expansion!

---
**Board FQBN:** `arduino:avr:mega`
**Baud Rate:** 9600
**Last Updated:** 2025-11-19
