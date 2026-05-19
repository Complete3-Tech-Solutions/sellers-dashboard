from __future__ import annotations

import hashlib
import logging
import threading
import time

from scc_agent.state import Store
from scc_agent.uploader import Uploader, sha256_file, with_retry
from scc_agent.watcher import list_xlsx

log = logging.getLogger(__name__)


class Syncer:
    def __init__(self, *, folder, uploader: Uploader, store: Store):
        self.folder = folder
        self.uploader = uploader
        self.store = store
        self._lock = threading.Lock()

    def folder_hash(self) -> str:
        return hashlib.sha256(str(self.folder.resolve()).encode()).hexdigest()

    def sync_once(self) -> dict:
        """Compute the diff between disk and our recorded state; upload changes; commit a snapshot."""
        if not self._lock.acquire(blocking=False):
            log.debug("sync already running, skipping")
            return {"skipped": True}
        try:
            current_files = list_xlsx(self.folder)
            changed = []
            for p in current_files:
                h = sha256_file(p)
                prev = self.store.get(p.name)
                if prev is None or prev.sha256 != h:
                    changed.append((p, h))
            current_names = {p.name for p in current_files}
            deleted = list(self.store.known_filenames() - current_names)

            if not changed and not deleted:
                log.debug("nothing to do")
                return {"changed": 0, "deleted": 0}

            log.info("starting snapshot: %d changed, %d deleted", len(changed), len(deleted))
            snapshot_id = with_retry(self.uploader.start_snapshot, self.folder_hash())
            manifest: list[dict] = []

            for path, h in changed:
                # File may be open in Excel; retry briefly to handle the share lock.
                for attempt in range(3):
                    try:
                        with_retry(self.uploader.upload_file, snapshot_id, path, h, max_attempts=3)
                        break
                    except PermissionError:
                        time.sleep(2)
                else:
                    raise RuntimeError(f"could not read {path.name} after retries")
                stat = path.stat()
                self.store.upsert(path.name, h, stat.st_size, stat.st_mtime)
                manifest.append({"filename": path.name, "sha256": h})

            for fname in deleted:
                manifest.append({"filename": fname, "sha256": None, "deleted": True})
                self.store.delete(fname)

            with_retry(self.uploader.commit_snapshot, snapshot_id, manifest)
            log.info("committed snapshot %s with %d entries", snapshot_id, len(manifest))
            return {"snapshot_id": snapshot_id, "changed": len(changed), "deleted": len(deleted)}
        finally:
            self._lock.release()
