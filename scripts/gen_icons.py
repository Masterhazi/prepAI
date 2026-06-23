"""
scripts/gen_icons.py - Generate all icon sizes required by Tauri.

Tauri requires these exact files in src-tauri/icons/:
  32x32.png         - Windows taskbar, small
  128x128.png       - Windows/Linux app icon
  128x128@2x.png    - macOS retina (256x256 pixels, named @2x)
  icon.ico          - Windows .exe icon (multi-size)
  icon.icns         - macOS .app icon (multi-size)
  icon.png          - source (already present, tray icon)

Run from repo root: python3 scripts/gen_icons.py
"""

import sys
import os
import struct
import io
from pathlib import Path

# Force UTF-8 so Unicode in filenames/paths does not crash on Windows cp1252
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

try:
    from PIL import Image
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "--quiet"])
    from PIL import Image

ICONS_DIR = Path("src-tauri/icons")
SOURCE    = ICONS_DIR / "icon.png"


def write_ico(img, path):
    """Write a proper multi-size .ico file (no Pillow ICO bugs)."""
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        buf = io.BytesIO()
        img.resize((sz, sz), Image.LANCZOS).save(buf, format="PNG")
        images.append((sz, buf.getvalue()))

    num = len(images)
    header = struct.pack("<HHH", 0, 1, num)

    offset = 6 + num * 16
    directory = b""
    for sz, data in images:
        w = sz if sz < 256 else 0
        h = sz if sz < 256 else 0
        directory += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(data), offset)
        offset += len(data)

    with open(path, "wb") as f:
        f.write(header + directory)
        for _, data in images:
            f.write(data)


def write_icns(img, path):
    """Write a proper .icns file for macOS."""
    # ICNS type codes -> pixel sizes
    types = [
        (b"icp4", 16),
        (b"icp5", 32),
        (b"icp6", 64),
        (b"ic07", 128),
        (b"ic08", 256),
        (b"ic09", 512),
    ]

    chunks = b""
    for type_code, size in types:
        target_size = min(size, max(img.size))
        resized = img.resize((target_size, target_size), Image.LANCZOS)
        buf = io.BytesIO()
        resized.save(buf, format="PNG")
        data = buf.getvalue()
        chunk_len = 8 + len(data)
        chunks += type_code + struct.pack(">I", chunk_len) + data

    total = 8 + len(chunks)
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", total) + chunks)


def main():
    if not SOURCE.exists():
        print("ERROR: source icon not found at " + str(SOURCE))
        sys.exit(1)

    img = Image.open(str(SOURCE)).convert("RGBA")
    print("Source: " + str(SOURCE) + " (" + str(img.size[0]) + "x" + str(img.size[1]) + ")")

    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # PNG sizes
    png_targets = [
        ("32x32.png",      32),
        ("128x128.png",    128),
        ("128x128@2x.png", 256),   # This was the missing one
    ]
    for name, size in png_targets:
        out = ICONS_DIR / name
        img.resize((size, size), Image.LANCZOS).save(str(out), format="PNG")
        print("[OK] " + str(out))

    # icon.ico for Windows
    ico_path = ICONS_DIR / "icon.ico"
    write_ico(img, ico_path)
    print("[OK] " + str(ico_path) + " (16,24,32,48,64,128,256)")

    # icon.icns for macOS
    icns_path = ICONS_DIR / "icon.icns"
    write_icns(img, icns_path)
    print("[OK] " + str(icns_path) + " (16,32,64,128,256,512)")

    print("")
    print("All icons generated successfully.")


if __name__ == "__main__":
    main()
