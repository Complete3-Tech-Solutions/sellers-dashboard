from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StartSnapshotIn(BaseModel):
    agent_version: str = Field(default="0.0.0")
    folder_path_hash: str | None = None


class StartSnapshotOut(BaseModel):
    snapshot_id: uuid.UUID
    expires_at: datetime


class ManifestEntry(BaseModel):
    filename: str
    sha256: str | None = None
    deleted: bool = False


class CommitSnapshotIn(BaseModel):
    manifest: list[ManifestEntry]


class CommitSnapshotOut(BaseModel):
    status: str
    job_id: str | None = None


class SnapshotStatusOut(BaseModel):
    id: uuid.UUID
    status: str
    file_count: int
    total_bytes: int
    error: str | None = None
    started_at: datetime
    committed_at: datetime | None = None
    parsed_at: datetime | None = None
