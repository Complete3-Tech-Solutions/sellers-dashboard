from __future__ import annotations

import pathlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class FileState:
    filename: str
    sha256: str
    size_bytes: int
    mtime: float


class Store:
    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._init()

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS file_state (
                    filename TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    uploaded_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT,
                    filename TEXT,
                    payload BLOB,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_try_at TEXT NOT NULL,
                    last_error TEXT
                );
                """
            )

    def get(self, filename: str) -> FileState | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT filename, sha256, size_bytes, mtime FROM file_state WHERE filename = ?",
                (filename,),
            ).fetchone()
        if not row:
            return None
        return FileState(**dict(row))

    def upsert(self, filename: str, sha256: str, size_bytes: int, mtime: float) -> None:
        with self._conn() as c:
            c.execute(
                """
                INSERT INTO file_state(filename, sha256, size_bytes, mtime, uploaded_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(filename) DO UPDATE SET
                    sha256=excluded.sha256,
                    size_bytes=excluded.size_bytes,
                    mtime=excluded.mtime,
                    uploaded_at=datetime('now')
                """,
                (filename, sha256, size_bytes, mtime),
            )

    def delete(self, filename: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM file_state WHERE filename = ?", (filename,))

    def known_filenames(self) -> set[str]:
        with self._conn() as c:
            rows = c.execute("SELECT filename FROM file_state").fetchall()
        return {r["filename"] for r in rows}
