"""Load the embedded 2013 dataset into a dev tenant.

Run: ``python -m app.seed``

Reads ``backend/app/seed_data.json`` (extracted from the original
``SCC_Profitability_Dashboard2.html``) and writes Projects / MonthlyMetric /
QuarterlyMetric / OverheadDetail rows for a tenant named "Dev Tenant" with
admin user ``dev@example.com`` / ``devpassword``. Set ``AUTO_SEED=true``
to run this automatically on backend startup (handy for first Railway deploy).
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import (
    MonthlyMetric,
    OverheadDetail,
    Project,
    QuarterlyMetric,
    Tenant,
    User,
)
from app.security import hash_password

DEV_EMAIL = os.environ.get("SEED_EMAIL", "dev@example.com")
DEV_PASSWORD = os.environ.get("SEED_PASSWORD", "devpassword")
DEV_TENANT = os.environ.get("SEED_TENANT", "Dev Tenant")

_here = pathlib.Path(__file__).resolve()
JSON_CANDIDATES = [
    _here.parent / "seed_data.json",            # backend/app/seed_data.json (Docker + local)
    _here.parents[2] / "SCC_Profitability_Dashboard2.html",  # fall back to extracting from HTML
]


def extract_data() -> dict:
    for p in JSON_CANDIDATES:
        if not p.exists():
            continue
        if p.suffix == ".json":
            return json.loads(p.read_text(encoding="utf-8"))
        html = p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"const\s+DATA\s*=\s*(\{.*?\})\s*;\s*let\s+currentYear", html, re.DOTALL)
        if m:
            return json.loads(m.group(1))
    raise FileNotFoundError("seed_data.json (or the source HTML) not found")


async def main() -> None:
    data = extract_data()
    async with SessionLocal() as session:
        res = await session.execute(select(Tenant).where(Tenant.slug == "dev"))
        tenant = res.scalar_one_or_none()
        if not tenant:
            tenant = Tenant(slug="dev", name=DEV_TENANT)
            session.add(tenant)
            await session.flush()

        res = await session.execute(
            select(User).where(User.tenant_id == tenant.id, User.email == DEV_EMAIL)
        )
        user = res.scalar_one_or_none()
        if not user:
            user = User(
                tenant_id=tenant.id,
                email=DEV_EMAIL,
                password_hash=hash_password(DEV_PASSWORD),
                role="admin",
            )
            session.add(user)

        for year_str, payload in data.items():
            year = int(year_str)
            # Replace existing data for this year (idempotent re-seeds)
            await session.execute(
                delete(Project).where(
                    Project.tenant_id == tenant.id, Project.fiscal_year == year
                )
            )
            await session.execute(
                delete(MonthlyMetric).where(
                    MonthlyMetric.tenant_id == tenant.id, MonthlyMetric.fiscal_year == year
                )
            )
            await session.execute(
                delete(QuarterlyMetric).where(
                    QuarterlyMetric.tenant_id == tenant.id,
                    QuarterlyMetric.fiscal_year == year,
                )
            )
            await session.execute(
                delete(OverheadDetail).where(
                    OverheadDetail.tenant_id == tenant.id,
                    OverheadDetail.fiscal_year == year,
                )
            )

            for p in payload.get("projects", []):
                # Some legacy rows use string sentinels for currency cols
                invoiced = p.get("invoiced")
                pmt = p.get("pmt_recd")
                if isinstance(invoiced, str):
                    invoiced = None
                if isinstance(pmt, str):
                    pmt = None
                session.add(
                    Project(
                        tenant_id=tenant.id,
                        fiscal_year=year,
                        job_no=str(p["job"]),
                        name=p["name"],
                        pct_compl=p.get("pct_compl"),
                        contract=p.get("contract"),
                        cost=p.get("cost"),
                        profit=p.get("profit"),
                        profit_pct=p.get("profit_pct"),
                        invoiced=invoiced,
                        pmt_recd=pmt,
                        last_month=p.get("last_month"),
                    )
                )
            for m in payload.get("monthly", []):
                session.add(
                    MonthlyMetric(
                        tenant_id=tenant.id,
                        fiscal_year=year,
                        month=m["month"],
                        gross_profit=m.get("gross_profit"),
                        overhead=m.get("overhead"),
                        net_profit=m.get("net_profit"),
                    )
                )
            for q in payload.get("quarterly", []):
                session.add(
                    QuarterlyMetric(
                        tenant_id=tenant.id,
                        fiscal_year=year,
                        quarter=q["quarter"],
                        sales=q.get("sales"),
                        gross_profit=q.get("gross_profit"),
                        gross_pct=q.get("gross_pct"),
                        overhead=q.get("overhead"),
                        overhead_pct=q.get("overhead_pct"),
                        net_profit=q.get("net_profit"),
                        net_pct=q.get("net_pct"),
                    )
                )
            for o in payload.get("overhead_detail", []):
                session.add(
                    OverheadDetail(
                        tenant_id=tenant.id,
                        fiscal_year=year,
                        month=o["month"],
                        overhead=o.get("overhead"),
                        computers=o.get("computers"),
                        furniture=o.get("furniture"),
                        total=o.get("total"),
                    )
                )

        await session.commit()

    print(f"Seeded {DEV_TENANT}. Login: {DEV_EMAIL} / {DEV_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
