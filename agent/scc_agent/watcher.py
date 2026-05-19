from __future__ import annotations

import logging
import os
import pathlib
import threading
from collections.abc import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)

XLSX_EXTS = (".xlsx", ".xlsm")


def _is_excel_temp(name: str) -> bool:
    return name.startswith("~$") or name.endswith((".tmp", "~"))


def list_xlsx(folder: pathlib.Path) -> list[pathlib.Path]:
    return sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in XLSX_EXTS and not _is_excel_temp(p.name)
    )


class FolderWatcher:
    def __init__(
        self,
        folder: pathlib.Path,
        debounce_secs: float,
        poll_interval: float,
        on_change: Callable[[], None],
    ):
        self.folder = folder
        self.debounce_secs = debounce_secs
        self.poll_interval = poll_interval
        self.on_change = on_change
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._observer: Observer | None = None

    def _trigger(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce_secs, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        try:
            self.on_change()
        except Exception:
            log.exception("on_change failed")

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.poll_interval):
            self._flush()

    def start(self) -> None:
        if not self.folder.exists():
            raise FileNotFoundError(self.folder)
        outer = self

        class H(FileSystemEventHandler):
            def on_any_event(self, event: FileSystemEvent) -> None:
                if event.is_directory:
                    return
                name = os.path.basename(event.src_path)
                if _is_excel_temp(name):
                    return
                if not name.lower().endswith(XLSX_EXTS):
                    return
                outer._trigger()

        self._observer = Observer()
        self._observer.schedule(H(), str(self.folder), recursive=False)
        self._observer.start()

        t = threading.Thread(target=self._poll_loop, daemon=True, name="scc-poll")
        t.start()
        log.info("watching %s (debounce=%ss, poll=%ss)", self.folder, self.debounce_secs, self.poll_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
        if self._timer is not None:
            self._timer.cancel()
