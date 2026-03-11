#!/bin/bash
# Monitor cable tester communication.
# Auto-detects platform: UNO Q (Bridge RPC) or Mega 2560 (serial).
#
# UNO Q:  Interactive RPC shell - type commands (ID, STATUS, CONT, etc.)
# Mega:   arduino-cli serial monitor at 9600 baud

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# --- Platform detection ---
if [[ -S /var/run/arduino-router.sock ]]; then
    PLATFORM="unoq"
elif ls /dev/ttyACM* &>/dev/null; then
    PLATFORM="mega"
else
    echo "ERROR: No Arduino hardware detected."
    exit 1
fi

echo "Platform: $PLATFORM"

if [[ "$PLATFORM" == "unoq" ]]; then
    # Interactive RPC command shell
    echo "UNO Q Bridge RPC monitor. Type commands (ID, STATUS, CONT, RES, etc.)"
    echo "Press Ctrl+C to exit."
    echo ""

    # Find python with msgpack
    PYTHON=""
    if [[ -f "$PROJECT_DIR/.venv/bin/python" ]]; then
        PYTHON="$PROJECT_DIR/.venv/bin/python"
    elif python3 -c "import msgpack" 2>/dev/null; then
        PYTHON="python3"
    else
        echo "ERROR: msgpack not available. Run: pip install msgpack"
        exit 1
    fi

    $PYTHON -c "
import socket, msgpack, sys

def rpc_call(cmd):
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect('/var/run/arduino-router.sock')
    sock.settimeout(15)
    msg = msgpack.packb([0, 1, 'run_command', [cmd]])
    sock.sendall(msg)
    data = sock.recv(4096)
    resp = msgpack.unpackb(data)
    sock.close()
    if resp[2] is not None:
        return f'ERROR: {resp[2]}'
    return resp[3]

while True:
    try:
        cmd = input('> ')
        if not cmd.strip():
            continue
        print(rpc_call(cmd.strip()))
    except (KeyboardInterrupt, EOFError):
        print()
        break
    except Exception as e:
        print(f'Error: {e}')
"

elif [[ "$PLATFORM" == "mega" ]]; then
    echo "Mega 2560 serial monitor (9600 baud). Press Ctrl+A then K to exit."
    arduino-cli monitor -p /dev/ttyACM0 -c baudrate=9600
fi
