from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session, set_tenant
from app.models import User
from app.security import decode_access_token


@dataclass
class CurrentUser:
    id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


async def get_current_user(
    request: Request,
    access_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> CurrentUser:
    # Allow either cookie or Authorization: Bearer header (useful for API/tests)
    token = access_token
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not_authenticated")
    try:
        claims = decode_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token") from exc

    user_id = uuid.UUID(claims["sub"])
    tenant_id = uuid.UUID(claims["tid"])
    role = claims.get("role", "member")

    user = await session.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user_missing")

    await set_tenant(session, tenant_id)
    return CurrentUser(id=user_id, tenant_id=tenant_id, role=role)


async def require_admin(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    return current


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"
