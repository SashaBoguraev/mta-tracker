#!/usr/bin/env bash
set -euo pipefail

# This helper sets up a Raspberry Pi so MyBus can run out of the box.
# It installs system dependencies, builds the rgbmatrix Python bindings,
# creates a virtual environment, and installs the Python requirements.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
PROJECT_ROOT="${SCRIPT_DIR%/scripts}"
cd "$PROJECT_ROOT"

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || true)}"
if [[ -z "$PYTHON_BIN" ]]; then
  echo "python3 is required but was not found in PATH" >&2
  exit 1
fi

FONT_DEST="$PROJECT_ROOT/fonts"
MATRIX_REPO_DIR="${HOME}/Desktop/rpi-rgb-led-matrix"

apt_packages=(
  python3-venv
  python3-dev
  build-essential
  libfreetype6-dev
  libjpeg-dev
  libopenjp2-7
  git
  cmake
  libwebp-dev
  pkg-config
  libssl-dev
)

echo "[mybus] Updating apt cache and installing system packages..."
sudo apt-get update
sudo apt-get install -y "${apt_packages[@]}"

if [[ -d "$MATRIX_REPO_DIR" ]]; then
  if [[ ! -d "$MATRIX_REPO_DIR/.git" ]]; then
    echo "[mybus] Removing invalid rpi-rgb-led-matrix directory and recloning..."
    rm -rf "$MATRIX_REPO_DIR"
    git clone https://github.com/hzeller/rpi-rgb-led-matrix "$MATRIX_REPO_DIR"
  fi
else
  echo "[mybus] Cloning hzeller/rpi-rgb-led-matrix..."
  git clone https://github.com/hzeller/rpi-rgb-led-matrix "$MATRIX_REPO_DIR"
fi

VENV_DIR="$PROJECT_ROOT/mybus-env"
if [[ -d "$VENV_DIR" ]]; then
  echo "[mybus] Reusing existing virtual environment at $VENV_DIR"
else
  echo "[mybus] Creating virtual environment..."
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt

VENV_PYTHON="$VENV_DIR/bin/python"

cd "$MATRIX_REPO_DIR"

echo "[mybus] Building rgbmatrix Python bindings..."
git pull --ff-only || true
make build-python PYTHON="$VENV_PYTHON"
make install-python PYTHON="$VENV_PYTHON"

cd "$PROJECT_ROOT"
mkdir -p "$FONT_DEST"
cp -u "$MATRIX_REPO_DIR/fonts/7x13.bdf" "$FONT_DEST/"

cat <<'EOF'

Setup complete! Activate the environment with:
  source mybus-env/bin/activate
Then run the monitor, optionally forcing the matrix backend:
  MYBUS_DISPLAY_BACKEND=matrix python MyBus.py
EOF
