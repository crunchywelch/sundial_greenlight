#!/bin/bash

# dev_env.sh: Create or activate the Python virtual environment
#
# IMPORTANT: This script must be SOURCED, not executed!
# Usage: source dev_env.sh   (or: . dev_env.sh)
#

ENV_DIR="venv"

# Check if script is being sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "❌ ERROR: This script must be SOURCED, not executed!"
    echo ""
    echo "Usage:"
    echo "  source dev_env.sh"
    echo "  or"
    echo "  . dev_env.sh"
    echo ""
    exit 1
fi

# Check if packages are already installed before installing
if ! dpkg -l | grep -q python3-venv; then
    echo "[+] Installing python3-venv..."
    sudo apt install python3-venv
fi

if ! dpkg -l | grep -q python3-pip; then
    echo "[+] Installing python3-pip..."
    sudo apt install python3-pip
fi

if [ ! -d "$ENV_DIR" ]; then
    echo "[+] Creating virtual environment in ./$ENV_DIR"
    python3 -m venv "$ENV_DIR"
    source "$ENV_DIR/bin/activate"
    echo "[+] Installing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "[+] Virtual environment created and activated."
else
    echo "[+] Activating existing virtual environment..."
    source "$ENV_DIR/bin/activate"
    echo "✅ Virtual environment activated."
fi

echo ""
echo "To deactivate: deactivate"
echo "Run the app with: python -m greenlight.main"
