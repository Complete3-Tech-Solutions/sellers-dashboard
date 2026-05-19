"""Credential storage. On Windows uses DPAPI (LocalMachine scope); falls back to obfuscated
local file on non-Windows for development."""
from __future__ import annotations

import base64
import json
import os
import pathlib
import sys
from typing import Optional

from scc_agent.config import CREDS_PATH, ensure_dirs

_DEV_KEY = b"dev-only-not-secure-key-32bytes!"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def save(key_id: str, secret: str, path: pathlib.Path | None = None) -> None:
    ensure_dirs()
    target = path or CREDS_PATH
    blob = json.dumps({"key_id": key_id, "secret": secret}).encode()
    if _is_windows():
        import win32crypt  # type: ignore

        enc = win32crypt.CryptProtectData(blob, None, None, None, None, 0x4)  # LOCAL_MACHINE
    else:
        enc = b"DEV1" + base64.b64encode(_xor(blob, _DEV_KEY))
    target.write_bytes(enc)
    try:
        os.chmod(target, 0o600)
    except Exception:
        pass


def load(path: pathlib.Path | None = None) -> tuple[str, str]:
    target = path or CREDS_PATH
    enc = target.read_bytes()
    if _is_windows() and not enc.startswith(b"DEV1"):
        import win32crypt  # type: ignore

        _, dec = win32crypt.CryptUnprotectData(enc, None, None, None, 0)
    else:
        dec = _xor(base64.b64decode(enc[4:]), _DEV_KEY)
    obj = json.loads(dec)
    return obj["key_id"], obj["secret"]


def try_load(path: pathlib.Path | None = None) -> Optional[tuple[str, str]]:
    try:
        return load(path)
    except FileNotFoundError:
        return None
