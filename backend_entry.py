"""
backend_entry.py — Sidecar entry point for Tauri.
Unlike launcher.py (which opened its own WebView2 window), this ONLY
starts the Flask server. Tauri's Rust shell handles the window,
tray, and notifications natively — Python just serves the API + UI.
"""

import sys
import os
import threading
from pathlib import Path


def resource_path(relative: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).parent
    return str(base / relative)


def get_data_dir() -> Path:
    """
    Persistent data directory. Tauri sidecars run from a managed location,
    so we always use the user's home directory for data — never next to
    the binary (which may be read-only once installed).
    """
    data_dir = Path.home() / ".prepai"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def main():
    root = resource_path(".")
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ["PREPAI_DATA_DIR"] = str(get_data_dir())
    os.environ["PREPAI_TAURI_MODE"] = "1"  # lets app.py skip auto browser-open

    from app import app
    from core.notifications import start_scheduler

    start_scheduler()

    print("PREPAI_BACKEND_READY", flush=True)  # Rust watches for this line
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
