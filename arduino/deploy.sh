#!/bin/bash
# Deploy cable tester sketch to the connected Arduino hardware.
# Auto-detects platform: UNO Q (App Studio) or Mega 2560 (arduino-cli).
#
# Usage:
#   ./deploy.sh              # compile + flash
#   ./deploy.sh --set-default  # (UNO Q only) also set as boot default

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

UNOQ_APP_NAME="user:cable-tester"
UNOQ_APP_DIR="$PROJECT_DIR/ArduinoApps/cable-tester"
UNOQ_DEFAULT_FILE="/var/lib/arduino-app-cli/default.app"

MEGA_SKETCH_DIR="$SCRIPT_DIR/cable_tester"
MEGA_FQBN="arduino:avr:mega"
MEGA_PORT="/dev/ttyACM0"

SET_DEFAULT=false
if [[ "$1" == "--set-default" ]]; then
    SET_DEFAULT=true
fi

# --- Platform detection ---
if [[ -S /var/run/arduino-router.sock ]]; then
    PLATFORM="unoq"
elif ls /dev/ttyACM* &>/dev/null; then
    PLATFORM="mega"
else
    echo "ERROR: No Arduino hardware detected."
    echo "  UNO Q: /var/run/arduino-router.sock not found"
    echo "  Mega:  /dev/ttyACM* not found"
    exit 1
fi

echo "Platform: $PLATFORM"

# --- Deploy ---
if [[ "$PLATFORM" == "unoq" ]]; then
    if [[ ! -d "$UNOQ_APP_DIR" ]]; then
        echo "ERROR: App directory not found: $UNOQ_APP_DIR"
        exit 1
    fi

    echo "Stopping cable-tester app..."
    sudo -u arduino arduino-app-cli app stop "$UNOQ_APP_NAME" 2>&1 || true

    echo "Compiling and flashing..."
    sudo -u arduino arduino-app-cli app start "$UNOQ_APP_NAME" 2>&1

    if [[ "$SET_DEFAULT" == true ]]; then
        echo "Setting as boot default..."
        echo "$UNOQ_APP_DIR" | sudo tee "$UNOQ_DEFAULT_FILE" > /dev/null
        echo "Default app set to: $(cat $UNOQ_DEFAULT_FILE)"
    fi

    echo "Done. Cable tester deployed to UNO Q."

elif [[ "$PLATFORM" == "mega" ]]; then
    if [[ ! -d "$MEGA_SKETCH_DIR" ]]; then
        echo "ERROR: Sketch directory not found: $MEGA_SKETCH_DIR"
        exit 1
    fi

    echo "Compiling..."
    arduino-cli compile --fqbn "$MEGA_FQBN" "$MEGA_SKETCH_DIR"

    echo "Uploading to $MEGA_PORT..."
    arduino-cli upload -p "$MEGA_PORT" --fqbn "$MEGA_FQBN" "$MEGA_SKETCH_DIR"

    echo "Done. Cable tester deployed to Mega 2560."
fi
