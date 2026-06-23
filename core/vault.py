"""
vault.py — Local encrypted key storage (AES-256 via Fernet)
All keys stay on the user's machine. Never sent anywhere.
"""

import os
import json
from pathlib import Path
from cryptography.fernet import Fernet


_DATA_DIR = os.environ.get("PREPAI_DATA_DIR")
VAULT_DIR = Path(_DATA_DIR) if _DATA_DIR else Path.home() / ".prepai"
VAULT_FILE = VAULT_DIR / "vault.enc"
KEY_FILE = VAULT_DIR / "vault.key"

KNOWN_KEYS = [
    "anthropic_api_key",
    "gemini_api_key",
    "groq_api_key",
    "leetcode_session_token",
    "hackerrank_api_key",
    "linkedin_cookie",
    "naukri_cookie",
]


def _ensure_vault_dir():
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    # Restrict directory permissions on Unix
    try:
        os.chmod(VAULT_DIR, 0o700)
    except Exception:
        pass


def _load_or_create_key() -> bytes:
    _ensure_vault_dir()
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        os.chmod(KEY_FILE, 0o600)
    except Exception:
        pass
    return key


def _fernet() -> Fernet:
    return Fernet(_load_or_create_key())


def _load_vault() -> dict:
    if not VAULT_FILE.exists():
        return {}
    try:
        raw = _fernet().decrypt(VAULT_FILE.read_bytes())
        return json.loads(raw)
    except Exception:
        return {}


def _save_vault(data: dict):
    _ensure_vault_dir()
    encrypted = _fernet().encrypt(json.dumps(data).encode())
    VAULT_FILE.write_bytes(encrypted)
    try:
        os.chmod(VAULT_FILE, 0o600)
    except Exception:
        pass


def set_key(name: str, value: str):
    """Store a key in the encrypted vault."""
    data = _load_vault()
    data[name] = value
    _save_vault(data)
    print(f"  [vault] '{name}' saved (encrypted).")


def get_key(name: str) -> str | None:
    """Retrieve a key from the vault. Returns None if not set."""
    return _load_vault().get(name)


def delete_key(name: str):
    data = _load_vault()
    if name in data:
        del data[name]
        _save_vault(data)
        print(f"  [vault] '{name}' deleted.")


def list_keys() -> dict:
    """Return all keys with masked values for display."""
    data = _load_vault()
    masked = {}
    for k, v in data.items():
        if len(v) > 8:
            masked[k] = v[:4] + "••••" + v[-4:]
        else:
            masked[k] = "••••••••"
    return masked


def is_set(name: str) -> bool:
    return bool(get_key(name))


def status() -> dict:
    """Return set/missing status for all known keys."""
    return {k: is_set(k) for k in KNOWN_KEYS}


if __name__ == "__main__":
    print("=== PrepAI Vault ===")
    print("Key status:")
    for k, v in status().items():
        icon = "✓" if v else "✗"
        print(f"  {icon}  {k}")
