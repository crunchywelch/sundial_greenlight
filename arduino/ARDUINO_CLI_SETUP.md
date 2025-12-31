# Arduino CLI Setup and Workflow

This guide covers setting up arduino-cli on the Raspberry Pi for programming the Greenlight Cable Tester Arduino Mega 2560.

## Installation (Already Completed)

Arduino CLI has been installed to `~/.local/bin/arduino-cli` and added to PATH in `dev_env.sh`.

### What was installed:
- arduino-cli version 1.3.1
- Arduino AVR core (includes Mega 2560 support)
- Required tools: avr-gcc, avrdude, serial-discovery

## Quick Reference

### Compile Sketch
```bash
cd arduino
arduino-cli compile --fqbn arduino:avr:mega cable_tester
```

### Upload to Arduino
```bash
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester
```

### Monitor Serial Output
```bash
arduino-cli monitor -p /dev/ttyACM0 -c baudrate=9600
```

### One-Line Deploy (Compile + Upload)
```bash
cd arduino && \
arduino-cli compile --fqbn arduino:avr:mega cable_tester && \
arduino-cli upload -p /dev/ttyACM0 --fqbn arduino:avr:mega cable_tester
```

## Board Configuration

**Board:** Arduino Mega 2560 R3
**FQBN:** `arduino:avr:mega`
**Processor:** ATmega2560
**Baud Rate:** 9600
**USB:** Built-in (CH340 or ATmega16U2 USB-to-serial chip)

## Finding the Serial Port

### List all connected serial devices:
```bash
arduino-cli board list
```

### Common serial port names:
- `/dev/ttyACM0` - **Arduino Mega 2560 (most common)**
- `/dev/ttyUSB0` - Some Mega clones with CH340 chip
- `/dev/ttyAMA0` - Raspberry Pi GPIO serial (not used for Arduino)

### Check which port is the Arduino:
```bash
ls -l /dev/ttyUSB* /dev/ttyACM*
# Or use dmesg after plugging in:
dmesg | tail -20
```

## Compilation Results

Current sketch stats for **Arduino Mega 2560**:
- **Program storage:** 12,404 bytes (4% of 253,952 bytes) ✅
- **Dynamic memory:** 1,744 bytes (21% of 8,192 bytes) ✅
- **Local variables:** 6,448 bytes remaining ✅

✅ **Excellent Memory Headroom:** The Mega 2560 provides plenty of space for future expansion!

### Why Mega 2560 vs Pro Mini?
| Feature | Pro Mini | Mega 2560 | Winner |
|---------|----------|-----------|--------|
| Flash Memory | 30KB | 253KB | Mega (8x more) |
| RAM | 2KB (85% used) | 8KB (21% used) | Mega (4x more) |
| USB | External adapter needed | Built-in | Mega |
| Digital Pins | 14 | 54 | Mega |
| Analog Pins | 6 | 16 | Mega |
| Cost | ~$5 | ~$15 | Pro Mini |

**Verdict:** Mega 2560 is the better choice for this application.

## Hardware Requirements

### USB Connection
The Arduino Mega 2560 has **built-in USB** - no external adapter needed!
- Simply connect USB cable from Raspberry Pi to Arduino
- Auto-reset works automatically via DTR signal
- Power can be supplied via USB (up to 500mA)

## Troubleshooting

### "Permission denied" error on /dev/ttyACM0
```bash
# Add your user to the dialout group:
sudo usermod -a -G dialout $USER
# Log out and back in for changes to take effect
```

### Arduino not detected
```bash
# Check if device appears:
lsusb
# Should show "Arduino SA Mega 2560" or "QinHeng CH340" device

# Check kernel messages:
dmesg | grep -i "usb\|serial\|tty"
# Should show: "cdc_acm X-X:1.0: ttyACM0: USB ACM device"
```

### Upload fails with "stk500v2_recv() programmer not responding"
- Verify correct serial port: `arduino-cli board list`
- Try different USB cable (some cables are power-only)
- Press RESET button on Arduino and try upload again
- Check baud rate (should be 115200 for Mega 2560 bootloader)
- Verify FQBN is `arduino:avr:mega` not `arduino:avr:mega2560`

### Compilation errors
```bash
# Update core index:
arduino-cli core update-index

# Reinstall AVR core:
arduino-cli core uninstall arduino:avr
arduino-cli core install arduino:avr
```

## Advanced Usage

### List installed cores:
```bash
arduino-cli core list
```

### List available boards:
```bash
arduino-cli board listall | grep -i "pro"
```

### Get detailed board info:
```bash
arduino-cli board details -b arduino:avr:pro
```

### Update everything:
```bash
arduino-cli core update-index
arduino-cli core upgrade
```

## Integration with Python Application

The Greenlight Python application (`greenlight/testing.py`) includes:

- **`ArduinoATmega32Tester`** class for real Arduino communication
- **`MockArduinoTester`** class for testing without hardware
- Auto-detection of Arduino on serial ports
- Command/response protocol implementation

### Enable real Arduino in config:
```python
# In greenlight/config.py:
USE_REAL_ARDUINO = True
ARDUINO_PORT = "/dev/ttyUSB0"  # or None for auto-detect
ARDUINO_BAUDRATE = 9600
```

## Testing the Arduino Connection

After uploading firmware, test communication:

```bash
# Using arduino-cli monitor:
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=9600

# Send test commands:
GET_UNIT_ID
GET_STATUS
TEST_CABLE
```

Expected responses:
```
ARDUINO_READY:UNIT_1
UNIT_ID:1
STATUS:READY:FIXTURE_UNKNOWN:VOLTAGE_4.98
TEST_RESULT:CONTINUITY:1:RESISTANCE:0.245:CAPACITANCE:156.2:POLARITY:1:OVERALL:1
```

## Production Deployment

### Initial Setup on New Raspberry Pi:
```bash
# 1. Install arduino-cli
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=~/.local/bin sh

# 2. Initialize and install AVR core
arduino-cli config init
arduino-cli core update-index
arduino-cli core install arduino:avr

# 3. Add to PATH in ~/.bashrc or use dev_env.sh
export PATH="$HOME/.local/bin:$PATH"

# 4. Install pyserial for Python integration
pip install pyserial
```

### Deploy Firmware Update:
```bash
cd /home/welch/projects/sundial_greenlight/arduino
arduino-cli compile --fqbn arduino:avr:pro:cpu=16MHzatmega328 cable_tester
arduino-cli upload -p /dev/ttyUSB0 --fqbn arduino:avr:pro:cpu=16MHzatmega328 cable_tester
```

## Resources

- [Arduino CLI Documentation](https://arduino.github.io/arduino-cli/)
- [Arduino Pro Mini Documentation](https://www.arduino.cc/en/Main/arduinoBoardProMini)
- [FTDI Driver Installation](https://ftdichip.com/drivers/)
- [Greenlight Testing Module](../greenlight/testing.py)

---

**Last Updated:** 2025-11-19
**Arduino CLI Version:** 1.3.1
**AVR Core Version:** 1.8.6
