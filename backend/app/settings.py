from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_async_pg(url: str) -> str:
    """Railway (and Heroku) inject DATABASE_URL as ``postgresql://``; SQLAlchemy needs
    ``postgresql+asyncpg://`` for the async engine."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # asyncpg doesn't understand ?sslmode=require (it uses ssl=true). Strip it.
    if "?sslmode=" in url:
        url = url.split("?sslmode=")[0]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"

    database_url: str = "postgresql+asyncpg://scc:dev@localhost:5432/scc"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        return _normalize_async_pg(v)

    jwt_private_key_pem: str = ""
    jwt_public_key_pem: str = ""
    jwt_access_ttl_seconds: int = 60 * 15
    jwt_refresh_ttl_seconds: int = 60 * 60 * 24 * 7

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "scc-saas-snapshots"
    r2_endpoint_url: str = ""

    kms_fernet_key: str = ""

    sentry_dsn_backend: str = ""
    postmark_server_token: str = ""

    cookie_domain: str = ""
    cookie_secure: bool = False

    allowed_origins: str = "http://localhost:8000"

    snapshot_max_file_mb: int = 50
    snapshot_open_ttl_seconds: int = 60 * 60
    hmac_timestamp_skew_seconds: int = 300
    nonce_ttl_seconds: int = 600

    rate_limit_login_per_minute: int = 5
    rate_limit_login_per_hour_email: int = 20
    rate_limit_register_per_hour: int = 5
    rate_limit_snapshot_per_minute: int = 60
    rate_limit_generic_per_minute: int = 600

    dashboard_cache_ttl_seconds: int = 60

    # Self-service tenant signup. This is a single-tenant deployment by default,
    # so the /register page and /auth/register-tenant endpoint are disabled.
    # Set ALLOW_REGISTRATION=true to re-enable multi-tenant onboarding.
    allow_registration: bool = False

    # When true, /api/snapshot/{id}/commit runs the parser inline instead of
    # enqueuing an RQ job. Useful for single-service deployments (e.g. Railway
    # without a separate worker plan). Defaults to true in dev.
    parser_inline: bool = True

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def dashboard_dir(self) -> str:
        import os
        import pathlib

        env_override = os.environ.get("DASHBOARD_DIR")
        if env_override:
            return env_override
        # Try a few candidate paths so this works in both local dev (repo root) and Docker (/app).
        here = pathlib.Path(__file__).resolve()
        candidates = [
            here.parents[2] / "dashboard",   # repo root / dashboard
            here.parents[1] / "dashboard",   # /app/dashboard inside Docker
            pathlib.Path("/app/dashboard"),
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return str(candidates[0])


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
