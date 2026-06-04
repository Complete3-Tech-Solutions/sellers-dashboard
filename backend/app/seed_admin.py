"""Bootstrap initial login users (an admin, optionally a member) — no demo data.

Run: ``python -m app.seed_admin``

Unlike :mod:`app.seed` (which loads the embedded 2013 dataset), this only
ensures a tenant and login users exist so people can log in on a fresh deploy:

* an **admin** (full admin-panel access), always, and
* a **member** (dashboard only), *only* when ``USER_EMAIL``/``USER_PASSWORD``
  are set — otherwise the admin adds everyone else from the admin panel.

Set ``AUTO_SEED_ADMIN=true`` to run this automatically on backend startup
(handy for the first Railway deploy). Configure via env vars:

* ``SEED_TENANT``        tenant display name (default ``Dev Tenant``)
* ``SEED_TENANT_SLUG``   tenant slug (default: ``dev`` — the tenant the demo
                         seeder and agent uploads use, so the seeded users see
                         existing data; falls back to slugified ``SEED_TENANT``)
* ``ADMIN_EMAIL``        (default ``admin@example.com``)
* ``ADMIN_PASSWORD``     (required outside dev; ``changeme-admin1`` in dev)
* ``USER_EMAIL``         (default ``user@example.com``)
* ``USER_PASSWORD``      (required outside dev; ``changeme-user1`` in dev)
* ``SEED_RESET_PASSWORD`` if truthy, reset passwords when the users exist
* ``SEED_REMOVE_EMAIL``  if set, delete this user from the tenant (e.g. the
                         legacy ``dev@example.com``); comma-separated for several

Idempotent: re-running with the same emails is a no-op (unless reset is on).
"""
from __future__ import annotations

import asyncio
import os
import re

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import Tenant, User
from app.security import hash_password
from app.settings import settings

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(name: str) -> str:
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "tenant"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _require_password(env_var: str, dev_default: str) -> str:
    password = os.environ.get(env_var)
    if password:
        return password
    if settings.env != "dev":
        raise RuntimeError(f"{env_var} must be set outside dev")
    return dev_default


async def _ensure_user(session, *, tenant_id, email: str, password: str, role: str, reset: bool) -> str:
    res = await session.execute(
        select(User).where(User.tenant_id == tenant_id, User.email == email)
    )
    user = res.scalar_one_or_none()
    if user is None:
        session.add(
            User(
                tenant_id=tenant_id,
                email=email,
                password_hash=hash_password(password),
                role=role,
            )
        )
        return "created"
    if reset:
        user.password_hash = hash_password(password)
        user.role = role
        return "password reset"
    return "already exists (unchanged)"


async def main() -> None:
    tenant_name = os.environ.get("SEED_TENANT", "Dev Tenant")
    # Default to the "dev" slug used by app.seed + agent uploads so the seeded
    # users join the tenant that already holds data (not a fresh empty one).
    slug = os.environ.get("SEED_TENANT_SLUG") or _slugify(tenant_name)
    if "SEED_TENANT_SLUG" not in os.environ and "SEED_TENANT" not in os.environ:
        slug = "dev"
    reset = _truthy(os.environ.get("SEED_RESET_PASSWORD"))
    remove = [e.strip() for e in os.environ.get("SEED_REMOVE_EMAIL", "").split(",") if e.strip()]

    admin_email = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    admin_password = _require_password("ADMIN_PASSWORD", "changeme-admin1")

    # The member user is optional — only seeded when USER_EMAIL/USER_PASSWORD
    # are provided. Admins can add everyone else from the admin panel.
    user_email = os.environ.get("USER_EMAIL")
    seed_member = bool(user_email or os.environ.get("USER_PASSWORD"))
    if seed_member:
        user_email = user_email or "user@example.com"
        user_password = _require_password("USER_PASSWORD", "changeme-user1")

    seeded_emails = {admin_email} | ({user_email} if seed_member else set())

    async with SessionLocal() as session:
        res = await session.execute(select(Tenant).where(Tenant.slug == slug))
        tenant = res.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(slug=slug, name=tenant_name)
            session.add(tenant)
            await session.flush()

        admin_action = await _ensure_user(
            session, tenant_id=tenant.id, email=admin_email,
            password=admin_password, role="admin", reset=reset,
        )
        user_action = None
        if seed_member:
            user_action = await _ensure_user(
                session, tenant_id=tenant.id, email=user_email,
                password=user_password, role="member", reset=reset,
            )

        removed = []
        for email in remove:
            if email in seeded_emails:
                continue  # never delete the users we just seeded
            res = await session.execute(
                delete(User).where(User.tenant_id == tenant.id, User.email == email)
            )
            if res.rowcount:
                removed.append(email)

        await session.commit()

    print(f"Tenant '{tenant_name}' (slug: {slug}):")
    print(f"  admin  {admin_email} — {admin_action}")
    if seed_member:
        print(f"  member {user_email} — {user_action}")
    if removed:
        print(f"  removed: {', '.join(removed)}")


if __name__ == "__main__":
    asyncio.run(main())
