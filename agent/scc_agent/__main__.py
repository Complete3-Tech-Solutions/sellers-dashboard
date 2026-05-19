from __future__ import annotations

import argparse
import logging
import pathlib
import signal
import sys
import threading

from scc_agent import __version__
from scc_agent.config import LOG_DIR, STATE_PATH, ensure_dirs, load_config
from scc_agent.creds import save as save_creds
from scc_agent.logging_setup import setup as setup_logging
from scc_agent.state import Store
from scc_agent.sync import Syncer
from scc_agent.uploader import Uploader
from scc_agent.watcher import FolderWatcher

log = logging.getLogger("scc-agent")


def _init_sentry(dsn: str | None) -> None:
    if not dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=dsn, release=f"scc-agent@{__version__}")
    except Exception:
        log.exception("sentry init failed")


def cmd_store_key(full_key: str) -> int:
    if "." not in full_key:
        print("error: API key must be of the form scc_live_xxx.yyy", file=sys.stderr)
        return 2
    key_id, secret = full_key.split(".", 1)
    save_creds(key_id, secret)
    print("Stored.")
    return 0


def cmd_run(config_path: pathlib.Path | None) -> int:
    ensure_dirs()
    cfg = load_config(config_path) if config_path else load_config()
    setup_logging(LOG_DIR, cfg.log_level)
    _init_sentry(cfg.sentry_dsn)

    log.info("scc-agent %s starting; watching %s", __version__, cfg.watch_folder)

    store = Store(STATE_PATH)
    uploader = Uploader(cfg.api_base_url)
    syncer = Syncer(folder=cfg.watch_folder, uploader=uploader, store=store)

    watcher = FolderWatcher(
        folder=cfg.watch_folder,
        debounce_secs=cfg.debounce_secs,
        poll_interval=cfg.poll_interval,
        on_change=syncer.sync_once,
    )

    stop_evt = threading.Event()

    def _shutdown(*_a):
        log.info("shutdown signal received")
        stop_evt.set()

    signal.signal(signal.SIGINT, _shutdown)
    try:
        signal.signal(signal.SIGTERM, _shutdown)
    except (AttributeError, ValueError):
        pass

    watcher.start()
    # Run an initial sync so we don't wait for the first edit
    try:
        syncer.sync_once()
    except Exception:
        log.exception("initial sync failed")

    stop_evt.wait()
    watcher.stop()
    log.info("stopped")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scc-agent", description="SCC profitability agent")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", type=pathlib.Path, help="Path to config.toml")

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Run the watcher (default)")
    store = sub.add_parser("store-key", help="Persist an API key via DPAPI")
    store.add_argument("api_key", help="Full key, of the form scc_live_xxx.yyy")

    # Legacy flag form used by the installer:
    parser.add_argument(
        "--store-key", dest="store_key_flag", help=argparse.SUPPRESS, default=None
    )

    args = parser.parse_args(argv)

    if args.store_key_flag:
        return cmd_store_key(args.store_key_flag)
    if args.cmd == "store-key":
        return cmd_store_key(args.api_key)
    # default: run
    return cmd_run(args.config)


if __name__ == "__main__":
    sys.exit(main())
