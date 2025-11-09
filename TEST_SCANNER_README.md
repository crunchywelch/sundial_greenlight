# Scanner Testing Guide

Use these test scripts to verify your Zebra DS2208 scanner is working before using the full application.

## Quick Test

### 1. Basic Input Test (Simplest)
```bash
python test_scanner.py
```

This will:
- ✅ Check if scanner is connected via USB
- ✅ Test basic input capture (scan or type)
- ✅ Show what data is received

**What to do:**
1. Run the script
2. Scan a barcode when prompted
3. You should see the scanned data appear immediately

### 2. Rich Console Test
```bash
python test_scanner_rich.py
```

This tests scanner input using the same Rich library the app uses.

**What to do:**
1. Run the script
2. Scan a barcode when you see the `►` prompt
3. The scanned data should appear

## Troubleshooting

### Scanner Not Detected via USB
```
⚠️  No Zebra/Symbol device found in USB devices
```

**Check:**
- Is the scanner plugged into a USB port?
- Try a different USB port
- Run `lsusb` to see all USB devices
- Look for "Symbol" or vendor ID `05e0:`

### Scanner Doesn't Type Anything
```
[Scanning but nothing appears]
```

**Possible issues:**
1. **Scanner not in USB HID mode**
   - Some scanners have multiple modes (USB Serial, USB HID)
   - Make sure it's in USB HID keyboard emulation mode
   - Check scanner manual for configuration barcodes

2. **Permissions issue**
   - Your user needs access to input devices
   - May need to add user to `input` group:
     ```bash
     sudo usermod -a -G input $USER
     # Then log out and log back in
     ```

3. **Scanner needs activation**
   - Try pressing the trigger button
   - Scanner may have gone to sleep

### Scanner Types But Not in the App
If the test scripts work but the app doesn't:
- The app may have a UI rendering issue
- Check the console output for errors
- Try running the app with debug logging:
  ```bash
  python -m greenlight.main 2>&1 | tee debug.log
  ```

## Expected Behavior

**Working scanner:**
```
[Test 1] Scan or type now:
► SD123456
  ✅ Received: 'SD123456'
  Length: 8 characters
  💡 This looks like a cable serial number!
```

**Manual typing also works:**
```
[Test 2] Scan or type now:
► TEST123
  ✅ Received: 'TEST123'
  Length: 7 characters
```

## Technical Details

The Zebra DS2208 scanner operates as a **USB HID (Human Interface Device)** in keyboard emulation mode:

1. Plugs into USB port
2. Registers as a keyboard to the system
3. When scanning, it "types" the barcode data
4. Automatically presses Enter when done
5. No special drivers needed - works like a keyboard

This means:
- ✅ Both scanner and manual keyboard input work identically
- ✅ No special software or drivers required
- ✅ Works on any system that recognizes USB keyboards
- ✅ Can capture input with standard `input()` function
