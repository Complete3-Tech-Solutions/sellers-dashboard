from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass


def _data_dir() -> pathlib.Path:
    base = os.environ.get("PROGRAMDATA") or os.path.expanduser("~")
    return pathlib.Path(base) / "SCCAgent"


DATA_DIR = _data_dir()
CONFIG_PATH = DATA_DIR / "config.toml"
CREDS_PATH = DATA_DIR / "creds.bin"
STATE_PATH = DATA_DIR / "state.db"
LOG_DIR = DATA_DIR / "logs"


@dataclass(frozen=True)
class Config:
    api_base_url: str
    watch_folder: pathlib.Path
    debounce_secs: float
    poll_interval: float
    log_level: str
    sentry_dsn: str | None = None


def load_config(path: pathlib.Path | None = None) -> Config:
    p = path or CONFIG_PATH
    if not p.exists():
        raise FileNotFoundError(f"Config not found at {p}. Run install.ps1 first.")
    with p.open("rb") as fp:
        raw = tomllib.load(fp)
    return Config(
        api_base_url=str(raw["api_base_url"]).rstrip("/"),
        watch_folder=pathlib.Path(str(raw["watch_folder"])),
        debounce_secs=float(raw.get("debounce_secs", 8)),
        poll_interval=float(raw.get("poll_interval", 30)),
        log_level=str(raw.get("log_level", "INFO")).upper(),
        sentry_dsn=raw.get("sentry_dsn") or None,
    )


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
