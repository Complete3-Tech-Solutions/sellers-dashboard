from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from app import __version__
from app.routers import admin, auth, dashboard, ingest, static
from app.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)


def _init_sentry() -> None:
    if not settings.sentry_dsn_backend:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn_backend, traces_sample_rate=0.05)
    except Exception:
        log.exception("sentry init failed")


_init_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("AUTO_SEED", "").lower() in {"1", "true", "yes"}:
        try:
            from app.seed import main as seed_main

            await seed_main()
            log.info("auto-seed complete")
        except Exception:
            log.exception("auto-seed failed (continuing)")
    yield


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if settings.cookie_secure:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        # CSP narrowly tuned to the dashboard's external CDN deps
        response.headers.setdefault(
            "Content-Security-Policy",
            (
                "default-src 'self'; "
                "img-src 'self' data:; "
                "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src https://fonts.gstatic.com; "
                "connect-src 'self'"
            ),
        )
        return response


app = FastAPI(title="SCC Profitability SaaS", version=__version__, lifespan=lifespan)

if settings.cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(ingest.router)
app.include_router(admin.router)
# Static must be last so /api/* routes match first.
app.include_router(static.router)


@app.get("/version", include_in_schema=False)
async def version() -> dict:
    return {"version": __version__, "env": os.getenv("ENV", settings.env)}
