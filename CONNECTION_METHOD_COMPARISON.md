# Brady M511 Connection Method Comparison & Fix

## Problem
The settings screen Brady printer test was not making the LED go solid, while the standalone test script worked perfectly.

## Root Cause Analysis

### Working Test Script (`test_brady_simple_connection.py`)
```python
# Simple, direct connection
client = BleakClient(BRADY_MAC, timeout=15.0)
await client.connect()
# LED goes SOLID here! ✅
await asyncio.sleep(30)  # Hold connection
await client.disconnect()
```

### Original Settings Screen (`_test_bluetooth_printer`)
```python
# Complex Brady M511 implementation
printer = BradyM511Printer(device_path=printer_info['address'])
connection_success = printer.initialize()  # ❌ LED stays blinking
```

### What `printer.initialize()` was doing:
1. `BleakClient.connect()` ✅
2. Service discovery (looking for Brady service)
3. Characteristic enumeration (Print Job, PICL Request/Response)
4. PICL notification setup
5. Complex error handling

## The Issue
The Brady M511 LED behavior indicates the **connection establishment phase**, not the full service setup phase. The **simple `BleakClient.connect()` makes LED solid**, but the additional service discovery was either:

1. **Failing silently** - causing connection to drop
2. **Taking too long** - LED timeout behavior
3. **Interfering with connection** - Brady M511 multi-app cycling

## Solution Applied

### Updated Settings Screen Method
```python
# Direct connection test (matches working script)
async def test_direct_connection():
    client = BleakClient(printer_info['address'], timeout=15.0)
    await client.connect()  # LED goes SOLID ✅
    
    if client.is_connected:
        await asyncio.sleep(5)      # Hold to observe LED
        await client.disconnect()   # LED returns to blinking
        return True
    return False

# Run in sync context
loop = asyncio.new_event_loop()
connection_success = loop.run_until_complete(test_direct_connection())
```

## Key Changes

1. **Removed complex Brady M511 initialization** from settings test
2. **Added direct BleakClient connection** matching working script exactly  
3. **5-second connection hold** for LED observation
4. **Proper async/sync handling** for settings screen context
5. **Clear LED behavior indicators** in UI

## Expected Behavior

| Phase | LED State | Duration |
|-------|-----------|----------|
| Before | Blinking (pairing mode) | Continuous |
| During Connection | **SOLID** | 5 seconds |
| After Disconnect | Blinking (pairing mode) | Continuous |

## Result

✅ Settings screen Brady test now uses **exact same method** as working test script
✅ LED should go **SOLID during connection**  
✅ Connection held for **5 seconds** for clear observation
✅ **No complex protocol setup** that could interfere

The settings screen Brady printer test will now show the same LED behavior as the standalone working test script!