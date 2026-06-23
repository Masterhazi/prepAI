#!/bin/bash
# build_tauri.sh — Build PrepAI as a native Tauri app locally.
#
# Requirements (install once):
#   - Rust:    https://rustup.rs
#   - Node.js: https://nodejs.org (v18+)
#   - Tauri prerequisites for your OS: https://v2.tauri.app/start/prerequisites/
#       Windows: Microsoft C++ Build Tools + WebView2 (usually preinstalled on Win 11)
#       macOS:   Xcode Command Line Tools (`xcode-select --install`)
#       Linux:   libwebkit2gtk-4.1-dev, libappindicator3-dev, librsvg2-dev, patchelf
#
# Usage:
#   chmod +x build_tauri.sh
#   ./build_tauri.sh

set -e

echo ""
echo "============================================"
echo "  PrepAI — Tauri Build"
echo "============================================"
echo ""

# ── Detect platform + target triple ───────────────────────────────────────────
OS="$(uname -s)"
case "$OS" in
  Linux*)   TARGET="x86_64-unknown-linux-gnu"; EXT="" ;;
  Darwin*)
    if [[ "$(uname -m)" == "arm64" ]]; then
      TARGET="aarch64-apple-darwin"
    else
      TARGET="x86_64-apple-darwin"
    fi
    EXT="" ;;
  MINGW*|MSYS*|CYGWIN*) TARGET="x86_64-pc-windows-msvc"; EXT=".exe" ;;
  *) echo "Unsupported OS: $OS"; exit 1 ;;
esac

echo "[1/6] Detected target: $TARGET"

# ── Install Python deps + build the sidecar binary ────────────────────────────
echo "[2/6] Installing Python dependencies..."
pip install -r requirements.txt --quiet
pip install pyinstaller --quiet --upgrade

echo "[3/6] Building Python sidecar binary..."
rm -rf build dist
pyinstaller prepai-backend.spec --noconfirm --clean

mkdir -p src-tauri/binaries
cp "dist/prepai-backend${EXT}" "src-tauri/binaries/prepai-backend-${TARGET}${EXT}"
chmod +x "src-tauri/binaries/prepai-backend-${TARGET}${EXT}" 2>/dev/null || true
echo "      Sidecar ready: src-tauri/binaries/prepai-backend-${TARGET}${EXT}"

# ── Install npm deps (Tauri CLI) ──────────────────────────────────────────────
echo "[4/6] Installing Tauri CLI..."
npm install --silent

# ── Generate full icon set from the source PNG (one-time, safe to re-run) ─────
echo "[5/6] Generating icon set..."
npx tauri icon ui/static/icons/logo.png 2>&1 | tail -5 || echo "      (icon generation skipped — using existing icons)"

# ── Build ──────────────────────────────────────────────────────────────────────
echo "[6/6] Building Tauri app..."
npx tauri build

echo ""
echo "============================================"
echo "  BUILD COMPLETE"
echo "  Output: src-tauri/target/release/bundle/"
echo "============================================"
echo ""
echo "Windows: bundle/nsis/*.exe or bundle/msi/*.msi"
echo "macOS:   bundle/dmg/*.dmg"
echo "Linux:   bundle/appimage/*.AppImage or bundle/deb/*.deb"
echo ""
