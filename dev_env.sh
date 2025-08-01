#!/bin/bash

# dev_env.sh: Create or activate the Python virtual environment

ENV_DIR="venv"

if [ ! -d "$ENV_DIR" ]; then
    echo "[+] Creating virtual environment in ./$ENV_DIR"
    python3 -m venv "$ENV_DIR"
    source "$ENV_DIR/bin/activate"
    echo "[+] Installing dependencies..."
    pip install --upgrade pip
    pip install -r requirements.txt
    echo "[+] Virtual environment is ready."
fi

echo "[+] Activating virtual environment..."
source "$ENV_DIR/bin/activate"

echo "[+] Run the app with: python -m greenlight.main"
