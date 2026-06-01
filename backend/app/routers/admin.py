from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, require_admin
from app.models import ApiKey, AuditLog, Snapshot, Tenant, User
from app.schemas.admin import (
    ApiKeyCreateIn,
    ApiKeyCreateOut,
    ApiKeyOut,
    AuditLogOut,
    SnapshotSummaryOut,
    UserAdminOut,
    UserInviteIn,
)
from app.security import encrypt_secret, hash_password, new_api_key, sha256_hex
from app.services import storage

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/api-keys", response_model=ApiKeyCreateOut, status_code=201)
async def create_api_key(
    body: ApiKeyCreateIn,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreateOut:
    full_key, key_id, secret = new_api_key()
    key = ApiKey(
        tenant_id=current.tenant_id,
        label=body.label,
        key_id=key_id,
        secret_hash=sha256_hex(secret),
        secret_ciphertext=encrypt_secret(secret),
        ip_allowlist=body.ip_allowlist,
    )
    session.add(key)
    session.add(
        AuditLog(
            action="key.issued",
            tenant_id=current.tenant_id,
            user_id=current.id,
            resource=key_id,
        )
    )
    await session.commit()
    return ApiKeyCreateOut(
        id=key.id, label=key.label, full_key=full_key, created_at=key.created_at
    )


@router.get("/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyOut]:
    res = await session.execute(
        select(ApiKey).where(ApiKey.tenant_id == current.tenant_id).order_by(desc(ApiKey.created_at))
    )
    return [
        ApiKeyOut(
            id=k.id,
            label=k.label,
            key_id=k.key_id,
            ip_allowlist=k.ip_allowlist,
            last_used_at=k.last_used_at,
            last_used_ip=str(k.last_used_ip) if k.last_used_ip else None,
            created_at=k.created_at,
            revoked_at=k.revoked_at,
        )
        for k in res.scalars().all()
    ]


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(
    key_id: uuid.UUID,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    key = await session.get(ApiKey, key_id)
    if not key or key.tenant_id != current.tenant_id:
        raise HTTPException(404, "key_not_found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(tz=timezone.utc)
        session.add(
            AuditLog(
                action="key.revoked",
                tenant_id=current.tenant_id,
                user_id=current.id,
                resource=key.key_id,
            )
        )
        await session.commit()
    return {"ok": True}


@router.get("/snapshots", response_model=list[SnapshotSummaryOut])
async def list_snapshots(
    limit: int = Query(50, ge=1, le=200),
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[SnapshotSummaryOut]:
    res = await session.execute(
        select(Snapshot)
        .where(Snapshot.tenant_id == current.tenant_id)
        .order_by(desc(Snapshot.started_at))
        .limit(limit)
    )
    return [
        SnapshotSummaryOut(
            id=s.id,
            status=s.status,
            file_count=s.file_count,
            total_bytes=s.total_bytes,
            error=s.error,
            started_at=s.started_at,
            committed_at=s.committed_at,
            parsed_at=s.parsed_at,
        )
        for s in res.scalars().all()
    ]


@router.get("/audit", response_model=list[AuditLogOut])
async def list_audit(
    limit: int = Query(100, ge=1, le=500),
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[AuditLogOut]:
    res = await session.execute(
        select(AuditLog)
        .where(AuditLog.tenant_id == current.tenant_id)
        .order_by(desc(AuditLog.at))
        .limit(limit)
    )
    return [
        AuditLogOut(
            id=a.id,
            action=a.action,
            resource=a.resource,
            user_id=a.user_id,
            api_key_id=a.api_key_id,
            ip=str(a.ip) if a.ip else None,
            at=a.at,
        )
        for a in res.scalars().all()
    ]


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    data = await file.read(2 * 1024 * 1024)  # 2 MB cap
    if not data:
        raise HTTPException(400, "empty_file")
    if not data.startswith(b"\x89PNG"):
        raise HTTPException(415, "not_png")

    key = f"tenants/{current.tenant_id}/logo.png"
    try:
        storage.put_bytes(key, data, content_type="image/png")
    except Exception as exc:
        raise HTTPException(502, f"storage_failed: {exc}") from exc

    tenant = await session.get(Tenant, current.tenant_id)
    if tenant:
        tenant.logo_r2_key = key
    session.add(
        AuditLog(
            action="logo.uploaded",
            tenant_id=current.tenant_id,
            user_id=current.id,
            resource=key,
        )
    )
    await session.commit()
    return {"ok": True, "key": key}


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> list[UserAdminOut]:
    res = await session.execute(
        select(User).where(User.tenant_id == current.tenant_id).order_by(User.created_at)
    )
    return [
        UserAdminOut(
            id=u.id,
            email=u.email,
            role=u.role,
            totp_enabled=u.totp_secret is not None,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        )
        for u in res.scalars().all()
    ]


@router.post("/users", status_code=201)
async def invite_user(
    body: UserInviteIn,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    existing = await session.execute(
        select(User).where(User.tenant_id == current.tenant_id, User.email == str(body.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "user_exists")
    user = User(
        tenant_id=current.tenant_id,
        email=str(body.email),
        password_hash=hash_password(body.password),
        role=body.role,
    )
    session.add(user)
    session.add(
        AuditLog(
            action="user.invited",
            tenant_id=current.tenant_id,
            user_id=current.id,
            resource=str(body.email),
        )
    )
    await session.commit()
    return {"id": str(user.id)}
