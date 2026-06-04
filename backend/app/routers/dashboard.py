from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import CurrentUser, get_current_user
from app.models import MonthlyMetric, OverheadDetail, Project, QuarterlyMetric
from app.redis_client import get_redis
from app.schemas.dashboard import DashboardOut, ProjectLifetimeOut, ProjectYearRow, YearsOut
from app.services.accounting import DEFAULT_MODE, aggregate
from app.settings import settings

router = APIRouter(prefix="/api", tags=["dashboard"])

MONTH_ORDER = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _job_to_native(s: str) -> str | int:
    """Match the original JSON shape: numeric job numbers are ints, others stay strings."""
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return s
    return s


@router.get("/years", response_model=YearsOut)
async def years(
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> YearsOut:
    res = await session.execute(
        select(Project.fiscal_year).where(Project.tenant_id == current.tenant_id).distinct()
    )
    yrs = sorted({int(r[0]) for r in res.all()})
    return YearsOut(years=yrs, default=yrs[-1] if yrs else None)


@router.get("/dashboard", response_model=DashboardOut)
async def dashboard(
    year: int = Query(..., ge=1900, le=2100),
    accounting: str = Query(DEFAULT_MODE, pattern="^(raw|poc|closeout)$"),
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DashboardOut:
    cache_key = f"dashboard:{current.tenant_id}:{year}:{accounting}"
    r = get_redis()
    cached = await r.get(cache_key)
    if cached:
        return DashboardOut(**json.loads(cached))

    proj_res = await session.execute(
        select(Project).where(
            Project.tenant_id == current.tenant_id, Project.fiscal_year == year
        )
    )
    projects = proj_res.scalars().all()
    if not projects:
        raise HTTPException(status_code=404, detail="no_data_for_year")

    monthly_res = await session.execute(
        select(MonthlyMetric).where(
            MonthlyMetric.tenant_id == current.tenant_id, MonthlyMetric.fiscal_year == year
        )
    )
    quarterly_res = await session.execute(
        select(QuarterlyMetric).where(
            QuarterlyMetric.tenant_id == current.tenant_id,
            QuarterlyMetric.fiscal_year == year,
        )
    )
    oh_res = await session.execute(
        select(OverheadDetail).where(
            OverheadDetail.tenant_id == current.tenant_id, OverheadDetail.fiscal_year == year
        )
    )

    monthly_rows = list(monthly_res.scalars().all())
    monthly_rows.sort(key=lambda m: MONTH_ORDER.index(m.month) if m.month in MONTH_ORDER else 99)
    quarterly_rows = sorted(quarterly_res.scalars().all(), key=lambda q: q.quarter)
    oh_rows = list(oh_res.scalars().all())
    oh_rows.sort(key=lambda m: MONTH_ORDER.index(m.month) if m.month in MONTH_ORDER else 99)

    projects_out: list[dict[str, Any]] = [
        {
            "job": _job_to_native(p.job_no),
            "name": p.name,
            "pct_compl": _num(p.pct_compl),
            "contract": _num(p.contract),
            "cost": _num(p.cost),
            "profit": _num(p.profit),
            "profit_pct": _num(p.profit_pct),
            "invoiced": _num(p.invoiced),
            "pmt_recd": _num(p.pmt_recd),
            "last_month": p.last_month,
        }
        for p in projects
    ]

    overhead_out = [
        {
            "month": o.month,
            "overhead": _num(o.overhead),
            "computers": _num(o.computers),
            "furniture": _num(o.furniture),
            "total": _num(o.total),
        }
        for o in oh_rows
    ]

    if accounting == "raw":
        # Use what the worker precomputed (matches the customer's spreadsheet totals).
        monthly_out = [
            {
                "month": m.month,
                "gross_profit": _num(m.gross_profit),
                "overhead": _num(m.overhead),
                "net_profit": _num(m.net_profit),
            }
            for m in monthly_rows
        ]
        quarterly_out = [
            {
                "quarter": q.quarter,
                "sales": _num(q.sales),
                "gross_profit": _num(q.gross_profit),
                "gross_pct": _num(q.gross_pct),
                "overhead": _num(q.overhead),
                "overhead_pct": _num(q.overhead_pct),
                "net_profit": _num(q.net_profit),
                "net_pct": _num(q.net_pct),
            }
            for q in quarterly_rows
        ]
        sales_total = sum((q["sales"] or 0) for q in quarterly_out)
        gross = sum((q["gross_profit"] or 0) for q in quarterly_out)
        oh_total = sum((q["overhead"] or 0) for q in quarterly_out)
        net = sum((q["net_profit"] or 0) for q in quarterly_out)
        totals = {
            "sales": sales_total,
            "gross_profit": gross,
            "gross_pct": (gross / sales_total) if sales_total else 0,
            "overhead": oh_total,
            "overhead_pct": (oh_total / sales_total) if sales_total else 0,
            "net_profit": net,
            "net_pct": (net / sales_total) if sales_total else 0,
        }
    else:
        overhead_by_month = {o.month: float(o.overhead or 0) for o in monthly_rows}
        monthly_out, quarterly_out, totals = aggregate(
            projects, mode=accounting, overhead_by_month=overhead_by_month
        )

    out = DashboardOut(
        year=year,
        accounting=accounting,
        projects=projects_out,
        monthly=monthly_out,
        quarterly=quarterly_out,
        overhead_detail=overhead_out,
        totals=totals,
    )
    await r.setex(cache_key, settings.dashboard_cache_ttl_seconds, out.model_dump_json())
    return out


@router.get("/projects/{job_no}", response_model=ProjectLifetimeOut)
async def project_lifetime(
    job_no: str,
    current: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProjectLifetimeOut:
    """Every year this job_no appears in, in fiscal-year order. Lets the UI
    show a project's trajectory across fiscal years (contract size changes,
    %-completion progress, latest month reported)."""
    res = await session.execute(
        select(Project)
        .where(Project.tenant_id == current.tenant_id, Project.job_no == job_no)
        .order_by(Project.fiscal_year.asc())
    )
    rows = res.scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="job_not_found")
    out_rows = [
        ProjectYearRow(
            fiscal_year=r.fiscal_year,
            last_month=r.last_month,
            pct_compl=_num(r.pct_compl),
            contract=_num(r.contract),
            cost=_num(r.cost),
            profit=_num(r.profit),
            profit_pct=_num(r.profit_pct),
            invoiced=_num(r.invoiced),
            pmt_recd=_num(r.pmt_recd),
        )
        for r in rows
    ]
    return ProjectLifetimeOut(
        job_no=job_no,
        name=rows[-1].name,  # latest known name
        first_year=rows[0].fiscal_year,
        last_year=rows[-1].fiscal_year,
        years=out_rows,
    )
