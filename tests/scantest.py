# scan_barcodes.py
# Detect a HID barcode scanner and read codes (no GUI focus needed).
# Works well over SSH.

from evdev import InputDevice, categorize, ecodes, list_devices
import os, sys, time, re

# Prefer exact Zebra/Symbol VID:PID if available
PREFERRED = (0x05e0, 0x1200)  # from your dmesg

# Accept only these characters in the final code (tighten to your format if known)
ACCEPT = re.compile(r'[A-Za-z0-9._\-\/]+')

# Flush the buffer if there's a brief idle after last key (covers scanners without ENTER)
IDLE_FLUSH_SEC = 0.08

# Minimal keymap; extend if your barcodes include other symbols
KEYMAP = {
    ecodes.KEY_0:'0', ecodes.KEY_1:'1', ecodes.KEY_2:'2', ecodes.KEY_3:'3',
    ecodes.KEY_4:'4', ecodes.KEY_5:'5', ecodes.KEY_6:'6', ecodes.KEY_7:'7',
    ecodes.KEY_8:'8', ecodes.KEY_9:'9',
    ecodes.KEY_A:'a', ecodes.KEY_B:'b', ecodes.KEY_C:'c', ecodes.KEY_D:'d', ecodes.KEY_E:'e',
    ecodes.KEY_F:'f', ecodes.KEY_G:'g', ecodes.KEY_H:'h', ecodes.KEY_I:'i', ecodes.KEY_J:'j',
    ecodes.KEY_K:'k', ecodes.KEY_L:'l', ecodes.KEY_M:'m', ecodes.KEY_N:'n', ecodes.KEY_O:'o',
    ecodes.KEY_P:'p', ecodes.KEY_Q:'q', ecodes.KEY_R:'r', ecodes.KEY_S:'s', ecodes.KEY_T:'t',
    ecodes.KEY_U:'u', ecodes.KEY_V:'v', ecodes.KEY_W:'w', ecodes.KEY_X:'x', ecodes.KEY_Y:'y',
    ecodes.KEY_Z:'z',
    ecodes.KEY_MINUS:'-', ecodes.KEY_DOT:'.', ecodes.KEY_SLASH:'/',
    ecodes.KEY_KP0:'0',ecodes.KEY_KP1:'1',ecodes.KEY_KP2:'2',ecodes.KEY_KP3:'3',ecodes.KEY_KP4:'4',
    ecodes.KEY_KP5:'5',ecodes.KEY_KP6:'6',ecodes.KEY_KP7:'7',ecodes.KEY_KP8:'8',ecodes.KEY_KP9:'9',
}

def list_input_devices():
    out = []
    for path in list_devices():
        dev = InputDevice(path)
        # vendor/product available via dev.info for USB devices
        vid = getattr(getattr(dev, "info", None), "vendor", 0)
        pid = getattr(getattr(dev, "info", None), "product", 0)
        out.append((path, dev.name or "?", vid, pid))
    return sorted(out, key=lambda t: t[0])

def choose_device():
    devices = list_input_devices()
    if not devices:
        print("No /dev/input/event* devices found.", file=sys.stderr)
        sys.exit(1)

    # Prefer exact VID:PID if present
    preferred = [t for t in devices if (t[2], t[3]) == PREFERRED]
    if len(preferred) == 1:
        path, name, vid, pid = preferred[0]
        return path, name, vid, pid

    # Otherwise, filter for likely keyboards named like a scanner
    likely = [t for t in devices if "scanner" in (t[1] or "").lower()]
    if len(likely) == 1:
        path, name, vid, pid = likely[0]
        return path, name, vid, pid

    # Prompt user to choose
    print("Select input device to read (likely your scanner):")
    for idx, (path, name, vid, pid) in enumerate(devices):
        print(f"  [{idx}] {path}  name='{name}'  vid:pid={vid:04x}:{pid:04x}")
    while True:
        try:
            i = int(input("Enter number: ").strip())
            if 0 <= i < len(devices):
                return devices[i]
        except Exception:
            pass
        print("Invalid selection, try again.")

def emit(buf):
    raw = ''.join(buf).strip()
    if not raw:
        return
    m = ACCEPT.search(raw)
    if m:
        print(m.group(0), flush=True)

def read_scanner(devpath):
    dev = InputDevice(devpath)
    print(f"Listening on {dev.path} ({dev.name})")
    buf, last = [], time.monotonic()

    # Nonblocking reads; periodically flush on idle
    while True:
        try:
            for ev in dev.read():
                last = time.monotonic()
                if ev.type != ecodes.EV_KEY:
                    continue
                key = categorize(ev)
                if key.keystate != key.key_down:
                    continue

                kc = key.keycode
                # Enter terminators (main and keypad); keycode might be list
                if (kc == 'KEY_ENTER') or (kc == 'KEY_KPENTER') or (isinstance(kc, list) and ('KEY_ENTER' in kc or 'KEY_KPENTER' in kc)):
                    emit(buf); buf.clear()
                    continue

                ch = KEYMAP.get(key.scancode)
                if ch:
                    buf.append(ch)

            # idle flush
            if buf and (time.monotonic() - last) >= IDLE_FLUSH_SEC:
                emit(buf); buf.clear()
            time.sleep(0.01)

        except BlockingIOError:
            # nothing pending; consider idle flush
            if buf and (time.monotonic() - last) >= IDLE_FLUSH_SEC:
                emit(buf); buf.clear()
            time.sleep(0.01)
        except KeyboardInterrupt:
            break

def main():
    path, name, vid, pid = choose_device()
    # Prefer stable by-id symlink if available (event numbers can change)
    byid = None
    try:
        for entry in os.listdir("/dev/input/by-id"):
            p = os.path.join("/dev/input/by-id", entry)
            if os.path.islink(p) and os.path.realpath(p).endswith(os.path.basename(path)):
                byid = p
                break
    except Exception:
        pass
    devpath = byid or path
    read_scanner(devpath)

if __name__ == "__main__":
    # Permissions note: /dev/input/event* is usually root:input 0660.
    # Add your user to 'input' group or run with sudo, or create a udev rule.
    main()

