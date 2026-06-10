from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class ApiKeyCreateIn(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    ip_allowlist: list[str] | None = None


class ApiKeyRotateIn(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=128)
    ip_allowlist: list[str] | None = None


class ApiKeyCreateOut(BaseModel):
    id: uuid.UUID
    label: str
    full_key: str  # shown ONCE
    created_at: datetime


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    label: str
    key_id: str
    ip_allowlist: list[str] | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    created_at: datetime
    revoked_at: datetime | None = None


class SnapshotSummaryOut(BaseModel):
    id: uuid.UUID
    status: str
    file_count: int
    total_bytes: int
    error: str | None = None
    started_at: datetime
    committed_at: datetime | None = None
    parsed_at: datetime | None = None


class AuditLogOut(BaseModel):
    id: int
    action: str
    resource: str | None
    user_id: uuid.UUID | None
    api_key_id: uuid.UUID | None
    ip: str | None
    at: datetime


class UserInviteIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=256)
    role: str = Field(default="member", pattern="^(admin|member)$")


class UserAdminOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    totp_enabled: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserUpdateIn(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|member)$")
    password: str | None = Field(default=None, min_length=10, max_length=256)
