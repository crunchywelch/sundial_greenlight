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
  ensure_pkg mosquitto

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
    # Only run pip when requirements.txt changed since the last successful
    # install (tracked by a hash stamp). pip install on every source costs
    # ~2.5s+ for no benefit when nothing changed. Use FORCE_DEPS=1 to override.
    REQ_STAMP="$ENV_DIR/.requirements.sha256"
    REQ_HASH="$(sha256sum requirements.txt | awk '{print $1}')"
    if [[ "${FORCE_DEPS:-0}" == "1" || ! -f "$REQ_STAMP" || "$(cat "$REQ_STAMP" 2>/dev/null)" != "$REQ_HASH" ]]; then
      echo "[+] Installing dependencies (requirements.txt changed)..."
      python -m pip install --upgrade pip -q
      if python -m pip install -r requirements.txt -q; then
        echo "$REQ_HASH" > "$REQ_STAMP"
      else
        echo "[!] Dependency install failed; will retry on next source."
      fi
    else
      echo "[+] Dependencies up to date (skipping pip)."
    fi
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

# Install arduino-cli if not found
if ! command -v arduino-cli >/dev/null 2>&1; then
  echo "[+] Installing arduino-cli..."
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
fi

echo ""
echo "To deactivate: deactivate"
echo "Run the app with: python -m greenlight.main"
echo "Arduino CLI: $(arduino-cli version 2>/dev/null || echo 'not found')"

