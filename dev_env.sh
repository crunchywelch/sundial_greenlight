#!/usr/bin/env bash
# dev_env.sh: Create or activate the Python virtual environment
# IMPORTANT: This script must be SOURCED, not executed!
# Usage: source dev_env.sh   (or: . dev_env.sh)

ENV_DIR="venv"

# Require sourcing
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "ERROR: This script must be SOURCED, not executed."
  echo "Usage: source dev_env.sh"
  return 1 2>/dev/null || exit 1
fi

# Only bootstrap if not explicitly skipped
if [[ "${SKIP_BOOTSTRAP:-0}" != "1" ]]; then
  ensure_pkg() {
    if ! dpkg -s "$1" >/dev/null 2>&1; then
      echo "[+] Installing $1..."
      sudo apt-get update -y
      sudo apt-get install -y "$1"
    fi
  }

  ensure_pkg python3-venv
  ensure_pkg python3-pip

  # Check if venv exists but is incomplete/corrupted
  if [[ -d "$ENV_DIR" && ! -f "$ENV_DIR/bin/activate" ]]; then
    echo "[!] Incomplete virtual environment detected, removing..."
    rm -rf "$ENV_DIR"
  fi

  if [[ ! -d "$ENV_DIR" ]]; then
    echo "[+] Creating virtual environment in ./$ENV_DIR"
    python3 -m venv "$ENV_DIR"
    echo "[+] Virtual environment created."
  fi

  # Activate and ensure deps are installed
  source "$ENV_DIR/bin/activate"
  if [[ -f requirements.txt ]]; then
    echo "[+] Checking dependencies..."
    python -m pip install --upgrade pip -q
    python -m pip install -r requirements.txt -q
  fi
fi

# Always activate the venv for callers
echo "[+] Activating existing virtual environment..."
source "$ENV_DIR/bin/activate"
echo "✅ Virtual environment activated."

# If you use a src/ layout, expose it
if [[ -d src ]]; then
  export PYTHONPATH="$(pwd)/src:${PYTHONPATH:-}"
fi

# Add arduino-cli to PATH
export PATH="$HOME/.local/bin:$PATH"

echo ""
echo "To deactivate: deactivate"
echo "Run the app with: python -m greenlight.main"
echo "Arduino CLI available: $(which arduino-cli 2>/dev/null || echo 'not found')"

