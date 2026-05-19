from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_client_ip, get_current_user
from app.models import AuditLog, RefreshToken, Tenant, User
from app.schemas.auth import (
    LoginIn,
    LoginOut,
    RegisterTenantIn,
    RegisterTenantOut,
    TotpEnrollOut,
    TotpVerifyIn,
    UserOut,
)
from app.security import (
    hash_password,
    hash_refresh_token,
    issue_access_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.services import rate_limit
from app.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "tenant"


def _set_auth_cookies(response: Response, access: str, refresh: str) -> None:
    common = dict(
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.cookie_domain or None,
        path="/",
    )
    response.set_cookie("access_token", access, max_age=settings.jwt_access_ttl_seconds, **common)
    response.set_cookie(
        "refresh_token", refresh, max_age=settings.jwt_refresh_ttl_seconds, **common
    )


def _clear_auth_cookies(response: Response) -> None:
    common = dict(domain=settings.cookie_domain or None, path="/")
    response.delete_cookie("access_token", **common)
    response.delete_cookie("refresh_token", **common)


async def _audit(
    session: AsyncSession,
    *,
    action: str,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    metadata: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            action=action,
            tenant_id=tenant_id,
            user_id=user_id,
            ip=ip,
            user_agent=user_agent,
            meta=metadata,
        )
    )


async def _issue_session(
    session: AsyncSession, user: User, response: Response, family_id: uuid.UUID | None = None
) -> None:
    access = issue_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role)
    refresh, refresh_hash = new_refresh_token()
    expires = datetime.now(tz=timezone.utc) + timedelta(seconds=settings.jwt_refresh_ttl_seconds)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            family_id=family_id or uuid.uuid4(),
            expires_at=expires,
        )
    )
    _set_auth_cookies(response, access, refresh)


@router.post("/register-tenant", response_model=RegisterTenantOut, status_code=201)
async def register_tenant(
    body: RegisterTenantIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> RegisterTenantOut:
    ip = get_client_ip(request)
    await rate_limit.enforce(
        f"rl:register:{ip}",
        limit=settings.rate_limit_register_per_hour,
        window_seconds=3600,
    )

    base_slug = _slugify(body.tenant_name)
    slug = base_slug
    suffix = 0
    while True:
        existing = await session.execute(select(Tenant).where(Tenant.slug == slug))
        if existing.scalar_one_or_none() is None:
            break
        suffix += 1
        slug = f"{base_slug}-{suffix}"

    tenant = Tenant(slug=slug, name=body.tenant_name)
    session.add(tenant)
    await session.flush()

    user = User(
        tenant_id=tenant.id,
        email=str(body.email),
        password_hash=hash_password(body.password),
        role="admin",
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="email_in_use") from exc

    await _issue_session(session, user, response)
    await _audit(
        session,
        action="tenant.registered",
        tenant_id=tenant.id,
        user_id=user.id,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return RegisterTenantOut(tenant_id=tenant.id, user_id=user.id)


@router.post("/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> LoginOut:
    ip = get_client_ip(request)
    await rate_limit.enforce(
        f"rl:login:ip:{ip}", limit=settings.rate_limit_login_per_minute, window_seconds=60
    )
    await rate_limit.enforce(
        f"rl:login:email:{body.email}",
        limit=settings.rate_limit_login_per_hour_email,
        window_seconds=3600,
    )

    res = await session.execute(select(User).where(User.email == str(body.email)))
    user = res.scalar_one_or_none()
    bad = HTTPException(status_code=401, detail="invalid_credentials")
    if not user or not verify_password(body.password, user.password_hash):
        await _audit(
            session,
            action="login.failed",
            ip=ip,
            user_agent=request.headers.get("user-agent"),
            metadata={"email": str(body.email)},
        )
        await session.commit()
        raise bad

    if user.totp_secret:
        if not body.totp or not pyotp.TOTP(user.totp_secret).verify(body.totp, valid_window=1):
            raise HTTPException(status_code=401, detail="totp_required")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    user.last_login_at = datetime.now(tz=timezone.utc)
    await _issue_session(session, user, response)
    await _audit(
        session,
        action="login.success",
        tenant_id=user.tenant_id,
        user_id=user.id,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()

    return LoginOut(
        user=UserOut(id=user.id, email=user.email, role=user.role, tenant_id=user.tenant_id)
    )


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="missing_refresh")
    token_hash = hash_refresh_token(refresh_token)
    res = await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=401, detail="invalid_refresh")

    now = datetime.now(tz=timezone.utc)
    if row.expires_at.replace(tzinfo=timezone.utc) < now or row.revoked_at is not None:
        # Theft detection: if revoked but re-used, revoke the whole family
        await session.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.family_id == row.family_id)
            .values(revoked_at=now)
        )
        await session.commit()
        _clear_auth_cookies(response)
        raise HTTPException(status_code=401, detail="refresh_revoked")

    user = await session.get(User, row.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="user_missing")

    # Rotate: revoke the old token, issue a new one within the same family
    row.revoked_at = now
    await _issue_session(session, user, response, family_id=row.family_id)
    await session.commit()
    return {"ok": True}


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if refresh_token:
        token_hash = hash_refresh_token(refresh_token)
        await session.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.token_hash == token_hash)
            .values(revoked_at=datetime.now(tz=timezone.utc))
        )
        await session.commit()
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await session.get(User, current.id)
    assert user is not None
    return UserOut(id=user.id, email=user.email, role=user.role, tenant_id=user.tenant_id)


@router.post("/2fa/enroll", response_model=TotpEnrollOut)
async def enroll_2fa(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TotpEnrollOut:
    user = await session.get(User, current.id)
    assert user is not None
    if user.totp_secret:
        raise HTTPException(status_code=400, detail="already_enrolled")
    secret = pyotp.random_base32()
    user.totp_secret = secret  # activated only when verified
    await session.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="SCC SaaS")
    return TotpEnrollOut(secret=secret, provisioning_uri=uri)


@router.post("/2fa/verify")
async def verify_2fa(
    body: TotpVerifyIn,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await session.get(User, current.id)
    assert user is not None
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="not_enrolled")
    if not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="invalid_code")
    return {"ok": True}


@router.post("/2fa/disable")
async def disable_2fa(
    body: TotpVerifyIn,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await session.get(User, current.id)
    assert user is not None
    if not user.totp_secret:
        return {"ok": True}
    if not pyotp.TOTP(user.totp_secret).verify(body.code, valid_window=1):
        raise HTTPException(status_code=400, detail="invalid_code")
    user.totp_secret = None
    await session.commit()
    return {"ok": True}
