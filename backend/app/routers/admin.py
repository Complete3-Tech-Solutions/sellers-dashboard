from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, require_admin
from app.models import ApiKey, AuditLog, RefreshToken, Snapshot, Tenant, User
from app.schemas.admin import (
    ApiKeyCreateIn,
    ApiKeyCreateOut,
    ApiKeyOut,
    ApiKeyRotateIn,
    AuditLogOut,
    SnapshotSummaryOut,
    UserAdminOut,
    UserInviteIn,
    UserUpdateIn,
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


@router.post("/api-keys/{key_id}/rotate", response_model=ApiKeyCreateOut, status_code=201)
async def rotate_api_key(
    key_id: uuid.UUID,
    body: ApiKeyRotateIn | None = None,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreateOut:
    """Revoke an existing key and issue a fresh one. Label and IP allowlist are
    carried over from the old key unless overridden in the request body. The
    agent must be reconfigured with the returned full_key."""
    old = await session.get(ApiKey, key_id)
    if not old or old.tenant_id != current.tenant_id:
        raise HTTPException(404, "key_not_found")

    if old.revoked_at is None:
        old.revoked_at = datetime.now(tz=UTC)

    label = body.label if body and body.label else old.label
    ip_allowlist = body.ip_allowlist if body is not None else old.ip_allowlist

    full_key, new_key_id, secret = new_api_key()
    key = ApiKey(
        tenant_id=current.tenant_id,
        label=label,
        key_id=new_key_id,
        secret_hash=sha256_hex(secret),
        secret_ciphertext=encrypt_secret(secret),
        ip_allowlist=ip_allowlist,
    )
    session.add(key)
    session.add(
        AuditLog(
            action="key.rotated",
            tenant_id=current.tenant_id,
            user_id=current.id,
            resource=f"{old.key_id}->{new_key_id}",
        )
    )
    await session.commit()
    return ApiKeyCreateOut(
        id=key.id, label=key.label, full_key=full_key, created_at=key.created_at
    )


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
        key.revoked_at = datetime.now(tz=UTC)
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


@router.post("/api-keys/{key_id}/activate", response_model=ApiKeyOut)
async def activate_api_key(
    key_id: uuid.UUID,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyOut:
    """Make this key the sole active one: un-revoke it if needed and revoke every
    other key in the tenant. No new secret is issued, so the agent must already
    hold this key for the switch to take effect."""
    key = await session.get(ApiKey, key_id)
    if not key or key.tenant_id != current.tenant_id:
        raise HTTPException(404, "key_not_found")

    now = datetime.now(tz=UTC)
    others = await session.execute(
        select(ApiKey).where(
            ApiKey.tenant_id == current.tenant_id,
            ApiKey.id != key_id,
            ApiKey.revoked_at.is_(None),
        )
    )
    for other in others.scalars().all():
        other.revoked_at = now
        session.add(
            AuditLog(
                action="key.revoked",
                tenant_id=current.tenant_id,
                user_id=current.id,
                resource=other.key_id,
            )
        )

    if key.revoked_at is not None:
        key.revoked_at = None
    session.add(
        AuditLog(
            action="key.activated",
            tenant_id=current.tenant_id,
            user_id=current.id,
            resource=key.key_id,
        )
    )
    await session.commit()
    return ApiKeyOut(
        id=key.id,
        label=key.label,
        key_id=key.key_id,
        ip_allowlist=key.ip_allowlist,
        last_used_at=key.last_used_at,
        last_used_ip=str(key.last_used_ip) if key.last_used_ip else None,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


@router.post("/api-keys/{key_id}/reinstate", response_model=ApiKeyOut)
async def reinstate_api_key(
    key_id: uuid.UUID,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyOut:
    """Un-revoke a previously revoked key. The same secret is preserved, so an
    agent that still holds this key reconnects without reinstalling it."""
    key = await session.get(ApiKey, key_id)
    if not key or key.tenant_id != current.tenant_id:
        raise HTTPException(404, "key_not_found")
    if key.revoked_at is not None:
        key.revoked_at = None
        session.add(
            AuditLog(
                action="key.reinstated",
                tenant_id=current.tenant_id,
                user_id=current.id,
                resource=key.key_id,
            )
        )
        await session.commit()
    return ApiKeyOut(
        id=key.id,
        label=key.label,
        key_id=key.key_id,
        ip_allowlist=key.ip_allowlist,
        last_used_at=key.last_used_at,
        last_used_ip=str(key.last_used_ip) if key.last_used_ip else None,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


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


async def _admin_count(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    res = await session.execute(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant_id, User.role == "admin")
    )
    return int(res.scalar_one())


async def _revoke_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Force a user to re-authenticate by revoking their refresh tokens."""
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(tz=UTC))
    )


@router.patch("/users/{user_id}")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdateIn,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if body.role is None and body.password is None:
        raise HTTPException(400, "no_changes")

    user = await session.get(User, user_id)
    if not user or user.tenant_id != current.tenant_id:
        raise HTTPException(404, "user_not_found")

    # Don't let the last admin demote themselves and lock the tenant out.
    if (
        body.role == "member"
        and user.role == "admin"
        and await _admin_count(session, current.tenant_id) <= 1
    ):
        raise HTTPException(409, "last_admin")

    actions: list[str] = []
    if body.role is not None and body.role != user.role:
        user.role = body.role
        actions.append(f"role.{body.role}")
        await _revoke_sessions(session, user.id)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        actions.append("password.reset")
        await _revoke_sessions(session, user.id)

    if actions:
        session.add(
            AuditLog(
                action="user.updated",
                tenant_id=current.tenant_id,
                user_id=current.id,
                resource=f"{user.email}:{'+'.join(actions)}",
            )
        )
    await session.commit()
    return {"ok": True, "changed": actions}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if user_id == current.id:
        raise HTTPException(400, "cannot_delete_self")

    user = await session.get(User, user_id)
    if not user or user.tenant_id != current.tenant_id:
        raise HTTPException(404, "user_not_found")

    if user.role == "admin" and await _admin_count(session, current.tenant_id) <= 1:
        raise HTTPException(409, "last_admin")

    email = user.email
    await session.delete(user)  # refresh_tokens cascade via FK
    session.add(
        AuditLog(
            action="user.deleted",
            tenant_id=current.tenant_id,
            user_id=current.id,
            resource=email,
        )
    )
    await session.commit()
    return {"ok": True}
