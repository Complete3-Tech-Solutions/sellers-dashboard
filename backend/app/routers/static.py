from __future__ import annotations

import pathlib

from fastapi import APIRouter, Cookie, HTTPException, Response
from fastapi.responses import FileResponse, RedirectResponse

from app.security import decode_access_token
from app.services import storage
from app.settings import settings

router = APIRouter(tags=["static"])

DASHBOARD_DIR = pathlib.Path(settings.dashboard_dir)
DEFAULT_LOGO = DASHBOARD_DIR / "assets" / "scc.png"


def _is_logged_in(access_token: str | None) -> bool:
    if not access_token:
        return False
    try:
        decode_access_token(access_token)
        return True
    except Exception:
        return False


@router.get("/", include_in_schema=False)
async def root(access_token: str | None = Cookie(default=None)):
    if not _is_logged_in(access_token):
        return RedirectResponse(url="/login", status_code=307)
    return FileResponse(DASHBOARD_DIR / "index.html")


@router.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse(DASHBOARD_DIR / "login.html")


@router.get("/assets/{path:path}", include_in_schema=False)
async def assets(path: str):
    target = (DASHBOARD_DIR / "assets" / path).resolve()
    if not str(target).startswith(str(DASHBOARD_DIR.resolve())):
        raise HTTPException(status_code=404)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target)


@router.get("/tenant-logo.png", include_in_schema=False)
async def tenant_logo(access_token: str | None = Cookie(default=None)):
    # We don't strictly require auth here so the dashboard's <img> works pre-render,
    # but we resolve the tenant from the access token if available.
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Tenant

    tenant_id = None
    if access_token:
        try:
            claims = decode_access_token(access_token)
            tenant_id = claims.get("tid")
        except Exception:
            tenant_id = None

    if tenant_id:
        async with SessionLocal() as session:
            res = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
            t = res.scalar_one_or_none()
            if t and t.logo_r2_key:
                try:
                    data = storage.get_bytes(t.logo_r2_key)
                    return Response(
                        data,
                        media_type="image/png",
                        headers={"Cache-Control": "private, max-age=3600"},
                    )
                except Exception:
                    pass

    if DEFAULT_LOGO.exists():
        return FileResponse(DEFAULT_LOGO, media_type="image/png")
    raise HTTPException(status_code=404)


@router.get("/health", include_in_schema=False)
async def health() -> dict:
    return {"ok": True}
