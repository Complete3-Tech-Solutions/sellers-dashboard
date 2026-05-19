from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.db import get_session, set_tenant
from app.deps import get_client_ip
from app.models import ApiKey, AuditLog, Snapshot, SnapshotFile
from app.redis_client import get_redis
from app.schemas.ingest import (
    CommitSnapshotIn,
    CommitSnapshotOut,
    SnapshotStatusOut,
    StartSnapshotIn,
    StartSnapshotOut,
)
from app.security import (
    decrypt_secret,
    hmac_message,
    hmac_verify,
    now_unix,
    sha256_hex,
)
from app.services import rate_limit, storage
from app.settings import settings

router = APIRouter(prefix="/api/snapshot", tags=["ingest"])

XLSX_MAGIC = b"PK\x03\x04"


class AgentAuth:
    """Resolved agent identity after HMAC verification."""

    def __init__(self, api_key: ApiKey, ip: str):
        self.api_key = api_key
        self.tenant_id = api_key.tenant_id
        self.ip = ip


async def verify_agent(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AgentAuth:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(401, "missing_authorization")
    token = auth_header.split(" ", 1)[1]
    if "." not in token:
        raise HTTPException(401, "malformed_token")
    key_id, secret = token.split(".", 1)

    ts = request.headers.get("x-timestamp")
    nonce = request.headers.get("x-nonce")
    signature = request.headers.get("x-signature")
    if not (ts and nonce and signature):
        raise HTTPException(401, "missing_signature_headers")
    try:
        ts_i = int(ts)
    except ValueError as exc:
        raise HTTPException(401, "bad_timestamp") from exc
    if abs(now_unix() - ts_i) > settings.hmac_timestamp_skew_seconds:
        raise HTTPException(401, "timestamp_out_of_range")

    res = await session.execute(select(ApiKey).where(ApiKey.key_id == key_id))
    api_key = res.scalar_one_or_none()
    if not api_key or api_key.revoked_at is not None:
        raise HTTPException(401, "invalid_key")

    ip = get_client_ip(request)
    if api_key.ip_allowlist:
        if ip not in api_key.ip_allowlist:
            raise HTTPException(403, "ip_not_allowed")

    if sha256_hex(secret) != api_key.secret_hash:
        raise HTTPException(401, "bad_secret")

    # Nonce replay protection
    r = get_redis()
    nonce_key = f"nonce:{key_id}:{nonce}"
    set_ok = await r.set(nonce_key, "1", ex=settings.nonce_ttl_seconds, nx=True)
    if not set_ok:
        raise HTTPException(401, "nonce_replay")

    # Body hash + HMAC verify (skip body for GETs; multipart re-reads below)
    body = await request.body() if request.method != "GET" else b""
    # For multipart uploads, body is the raw multipart payload — we sign sha256 of that.
    msg = hmac_message(request.method, request.url.path, ts, nonce, body)
    expected_secret = decrypt_secret(api_key.secret_ciphertext)
    if not hmac_verify(expected_secret, msg, signature):
        raise HTTPException(401, "bad_signature")

    api_key.last_used_at = datetime.now(tz=timezone.utc)
    api_key.last_used_ip = ip

    await rate_limit.enforce(
        f"rl:snap:{key_id}",
        limit=settings.rate_limit_snapshot_per_minute,
        window_seconds=60,
    )

    await set_tenant(session, api_key.tenant_id)
    return AgentAuth(api_key=api_key, ip=ip)


def _r2_key(tenant_id: uuid.UUID, snapshot_id: uuid.UUID, filename: str) -> str:
    return f"tenants/{tenant_id}/snapshots/{snapshot_id}/{filename}"


@router.post("/start", response_model=StartSnapshotOut)
async def start_snapshot(
    body: StartSnapshotIn,
    auth: AgentAuth = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
) -> StartSnapshotOut:
    snap = Snapshot(tenant_id=auth.tenant_id, api_key_id=auth.api_key.id, status="open")
    session.add(snap)
    session.add(
        AuditLog(
            action="snapshot.start",
            tenant_id=auth.tenant_id,
            api_key_id=auth.api_key.id,
            ip=auth.ip,
            meta={"agent_version": body.agent_version},
        )
    )
    await session.commit()
    expires = snap.started_at + timedelta(seconds=settings.snapshot_open_ttl_seconds)
    return StartSnapshotOut(snapshot_id=snap.id, expires_at=expires)


@router.post("/{snapshot_id}/file")
async def upload_file(
    snapshot_id: uuid.UUID,
    request: Request,
    auth: AgentAuth = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    # Parse the multipart form ourselves so FastAPI's auto-parser doesn't
    # drain the request stream before verify_agent (which needs the raw body
    # to validate the HMAC signature). verify_agent has already read+cached
    # the body via request.body(), so request.form() uses the cache.
    form = await request.form()
    filename = form.get("filename")
    sha256 = form.get("sha256")
    file = form.get("file")
    if not isinstance(filename, str) or not isinstance(sha256, str):
        raise HTTPException(400, "missing_form_field")
    if not isinstance(file, UploadFile):
        raise HTTPException(400, "missing_file")

    snap = await session.get(Snapshot, snapshot_id)
    if not snap or snap.tenant_id != auth.tenant_id:
        raise HTTPException(404, "snapshot_not_found")
    if snap.status != "open":
        raise HTTPException(409, "snapshot_not_open")

    max_bytes = settings.snapshot_max_file_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large")
    if not data.startswith(XLSX_MAGIC):
        raise HTTPException(415, "not_xlsx")

    actual = hashlib.sha256(data).hexdigest()
    if actual != sha256:
        raise HTTPException(400, "sha256_mismatch")

    key = _r2_key(auth.tenant_id, snap.id, filename)
    try:
        storage.put_bytes(
            key,
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as exc:
        raise HTTPException(502, f"storage_failed: {exc}") from exc

    # Upsert snapshot_files (replace if same filename re-uploaded mid-snapshot)
    existing = await session.execute(
        select(SnapshotFile).where(
            SnapshotFile.snapshot_id == snap.id, SnapshotFile.filename == filename
        )
    )
    row = existing.scalar_one_or_none()
    if row:
        row.sha256 = actual
        row.size_bytes = len(data)
        row.r2_key = key
    else:
        session.add(
            SnapshotFile(
                snapshot_id=snap.id,
                filename=filename,
                sha256=actual,
                size_bytes=len(data),
                r2_key=key,
            )
        )
        snap.file_count += 1
    snap.total_bytes += len(data)
    await session.commit()
    return {"ok": True, "size": len(data)}


@router.post("/{snapshot_id}/commit", response_model=CommitSnapshotOut, status_code=202)
async def commit_snapshot(
    snapshot_id: uuid.UUID,
    body: CommitSnapshotIn,
    auth: AgentAuth = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
) -> CommitSnapshotOut:
    snap = await session.get(Snapshot, snapshot_id)
    if not snap or snap.tenant_id != auth.tenant_id:
        raise HTTPException(404, "snapshot_not_found")
    if snap.status != "open":
        raise HTTPException(409, "snapshot_not_open")

    res = await session.execute(
        select(SnapshotFile).where(SnapshotFile.snapshot_id == snap.id)
    )
    uploaded = {f.filename: f for f in res.scalars().all()}

    expected_present = {m.filename for m in body.manifest if not m.deleted}
    actual_present = set(uploaded.keys())
    missing = expected_present - actual_present
    extras = actual_present - expected_present
    if missing or extras:
        raise HTTPException(
            400,
            f"manifest_mismatch missing={sorted(missing)} extras={sorted(extras)}",
        )

    # sha256 check
    for m in body.manifest:
        if m.deleted:
            continue
        f = uploaded.get(m.filename)
        if not f or (m.sha256 and f.sha256 != m.sha256):
            raise HTTPException(400, f"sha256_mismatch_for_{m.filename}")

    snap.status = "committed"
    snap.committed_at = datetime.now(tz=timezone.utc)

    job_id = str(uuid.uuid4())
    session.add(
        AuditLog(
            action="snapshot.commit",
            tenant_id=auth.tenant_id,
            api_key_id=auth.api_key.id,
            ip=auth.ip,
            resource=str(snap.id),
            meta={"file_count": snap.file_count, "job_id": job_id},
        )
    )
    await session.commit()

    if settings.parser_inline:
        # Single-service mode (Railway free tier / testing): parse synchronously.
        # Slow snapshots will block the request but the agent doesn't care — it polls.
        import asyncio

        from app.workers.parse_snapshot import parse_snapshot_job

        try:
            await asyncio.to_thread(parse_snapshot_job, str(snap.id))
        except Exception:
            # parse_snapshot_job already records the error on the snapshot row.
            pass
        return CommitSnapshotOut(status="parsed", job_id=job_id)

    # Enqueue parser job (lazy import to avoid hard dep at startup)
    try:
        from redis import from_url as redis_from_url
        from rq import Queue

        q = Queue("snapshots", connection=redis_from_url(settings.redis_url))
        q.enqueue("app.workers.parse_snapshot.parse_snapshot_job", str(snap.id), job_id=job_id)
    except Exception:
        # Worker may not be running locally; status endpoint still reports 'committed'.
        pass

    return CommitSnapshotOut(status="queued", job_id=job_id)


@router.get("/{snapshot_id}", response_model=SnapshotStatusOut)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    auth: AgentAuth = Depends(verify_agent),
    session: AsyncSession = Depends(get_session),
) -> SnapshotStatusOut:
    snap = await session.get(Snapshot, snapshot_id)
    if not snap or snap.tenant_id != auth.tenant_id:
        raise HTTPException(404, "snapshot_not_found")
    return SnapshotStatusOut(
        id=snap.id,
        status=snap.status,
        file_count=snap.file_count,
        total_bytes=snap.total_bytes,
        error=snap.error,
        started_at=snap.started_at,
        committed_at=snap.committed_at,
        parsed_at=snap.parsed_at,
    )
