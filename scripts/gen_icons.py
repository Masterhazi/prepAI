"""
scripts/gen_icons.py — Generate all icon sizes required by Tauri.

Tauri requires these exact files in src-tauri/icons/:
  32x32.png          — Windows taskbar, small
  128x128.png        — Windows/Linux app icon
  128x128@2x.png     — macOS retina (256x256 pixels, named @2x)
  icon.ico           — Windows .exe icon (multi-size)
  icon.icns          — macOS .app icon (multi-size)
  icon.png           — Tray icon source

Run from repo root:  python3 scripts/gen_icons.py
"""

import os
import struct
import zlib
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "--quiet"])
    from PIL import Image

ICONS_DIR = Path("src-tauri/icons")
SOURCE    = ICONS_DIR / "icon.png"


def make_png_bytes(img: Image.Image, size: int) -> bytes:
    """Resize image and return raw PNG bytes."""
    import io
    buf = io.BytesIO()
    img.resize((size, size), Image.LANCZOS).save(buf, format="PNG")
    return buf.getvalue()


def write_ico(img: Image.Image, path: Path):
    """Write a proper multi-size .ico file."""
    import io
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for sz in sizes:
        buf = io.BytesIO()
        resized = img.resize((sz, sz), Image.LANCZOS)
        resized.save(buf, format="PNG")
        images.append((sz, buf.getvalue()))

    # ICO header
    num = len(images)
    header = struct.pack("<HHH", 0, 1, num)  # reserved, type=1(icon), count

    # Directory entries (each 16 bytes)
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


def write_icns(img: Image.Image, path: Path):
    """Write a proper .icns file for macOS."""
    import io

    # ICNS type codes → pixel sizes
    types = [
        (b"icp4", 16),
        (b"icp5", 32),
        (b"icp6", 64),
        (b"ic07", 128),
        (b"ic08", 256),
        (b"ic09", 512),
        (b"ic10", 1024),
        (b"ic11", 32),   # @2x of 16
        (b"ic12", 64),   # @2x of 32
        (b"ic13", 256),  # @2x of 128
        (b"ic14", 512),  # @2x of 256
    ]

    chunks = b""
    for type_code, size in types:
        if size > max(img.size):
            # Don't upscale beyond source resolution
            resized = img.resize((max(img.size), max(img.size)), Image.LANCZOS)
        else:
            resized = img.resize((size, size), Image.LANCZOS)
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
        print(f"ERROR: source icon not found at {SOURCE}")
        raise SystemExit(1)

    img = Image.open(SOURCE).convert("RGBA")
    print(f"Source: {SOURCE} ({img.size[0]}x{img.size[1]})")

    ICONS_DIR.mkdir(parents=True, exist_ok=True)

    # ── PNG sizes ──────────────────────────────────────────────────────────────
    png_targets = {
        "32x32.png":       32,
        "128x128.png":     128,
        "128x128@2x.png":  256,   # This is the one that was missing
    }
    for name, size in png_targets.items():
        out = ICONS_DIR / name
        img.resize((size, size), Image.LANCZOS).save(out, format="PNG")
        print(f"  ✓ {out}")

    # ── icon.ico (Windows) ─────────────────────────────────────────────────────
    write_ico(img, ICONS_DIR / "icon.ico")
    print(f"  ✓ {ICONS_DIR}/icon.ico  (multi-size: 16,24,32,48,64,128,256)")

    # ── icon.icns (macOS) ──────────────────────────────────────────────────────
    write_icns(img, ICONS_DIR / "icon.icns")
    print(f"  ✓ {ICONS_DIR}/icon.icns  (multi-size: 16–1024)")

    print("\nAll icons generated successfully.")


if __name__ == "__main__":
    main()
