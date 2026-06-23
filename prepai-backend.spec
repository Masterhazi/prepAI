# prepai-backend.spec — Builds the Flask backend as a standalone binary
# This is the "sidecar" that Tauri spawns and controls.
# Unlike prepai.spec (which built launcher.py + webview), this builds
# ONLY the Flask server — Tauri's Rust shell handles the window now.
#
# Usage: pyinstaller prepai-backend.spec --noconfirm --clean
# Output: dist/prepai-backend(.exe)
#
# Tauri requires sidecar binaries to be named with the target triple suffix,
# e.g. prepai-backend-x86_64-pc-windows-msvc.exe — the build script (CI)
# handles renaming after this builds.

import sys

datas = [
    ("ui/templates/index.html", "ui/templates"),
]

hidden_imports = [
    "flask", "flask.templating", "jinja2", "jinja2.ext",
    "werkzeug", "werkzeug.serving", "werkzeug.routing", "werkzeug.exceptions", "click",
    "anthropic", "anthropic._models", "anthropic.types", "httpx", "httpcore",
    "google.genai", "google.genai.types", "google.auth", "google.auth.transport",
    "groq",
    "cryptography", "cryptography.fernet",
    "cryptography.hazmat.primitives.kdf.pbkdf2", "cryptography.hazmat.backends.openssl",
    "plyer", "plyer.platforms",
    "plyer.platforms.win.notification", "plyer.platforms.macosx.notification",
    "plyer.platforms.linux.notification",
    "sqlalchemy", "sqlalchemy.pool", "sqlalchemy.orm",
    "pdfplumber", "docx", "fitz",
    "threading", "webbrowser", "json", "pathlib", "socket",
    "schedule", "requests", "urllib3", "certifi", "charset_normalizer",
]

a = Analysis(
    ["backend_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy", "cv2",
        "torch", "tensorflow", "IPython", "notebook", "jupyter",
        "PyQt5", "PyQt6", "wx", "test", "unittest",
        # No webview/pystray needed — Tauri handles the window + tray now
        "webview", "pystray",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name="prepai-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,    # Tauri captures stdout/stderr — keep console for logging
    onefile=True,    # Single binary — required for Tauri sidecar
)
