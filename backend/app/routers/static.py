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


def _decode_token(access_token: str | None) -> dict | None:
    if not access_token:
        return None
    try:
        return decode_access_token(access_token)
    except Exception:
        return None


@router.get("/", include_in_schema=False)
async def root(access_token: str | None = Cookie(default=None)):
    claims = _decode_token(access_token)
    if not claims:
        return RedirectResponse(url="/login", status_code=302)
    return FileResponse(DASHBOARD_DIR / "index.html")


@router.get("/login", include_in_schema=False)
async def login_page(access_token: str | None = Cookie(default=None)):
    claims = _decode_token(access_token)
    if claims:
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(DASHBOARD_DIR / "login.html")


@router.get("/admin", include_in_schema=False)
async def admin_page(access_token: str | None = Cookie(default=None)):
    claims = _decode_token(access_token)
    if not claims:
        return RedirectResponse(url="/login", status_code=302)
    if claims.get("role") != "admin":
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(DASHBOARD_DIR / "admin.html")


@router.get("/register", include_in_schema=False)
async def register_page(access_token: str | None = Cookie(default=None)):
    if not settings.allow_registration:
        return RedirectResponse(url="/login", status_code=302)
    claims = _decode_token(access_token)
    if claims:
        return RedirectResponse(url="/", status_code=302)
    return FileResponse(DASHBOARD_DIR / "register.html")


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
