"""Accounting-mode rollups for the dashboard.

A project's headline numbers in the SCC Profit Summary spreadsheets are the
*full* contract value and *full* projected profit, repeated in every year the
project is open. That matches how the customer's existing reports read, but
double-counts work that spans fiscal years. These functions compute alternate
views from the stored ``projects`` rows so the dashboard can offer:

- ``raw``       — the spreadsheet's own view (default). Each project contributes
                  its full contract + profit to whatever year it appears in.
                  Identical to the precomputed ``monthly_metrics`` /
                  ``quarterly_metrics`` rows the worker wrote.
- ``poc``       — percentage-of-completion. Each project contributes
                  ``contract × pct_compl`` and ``profit × pct_compl`` to its year.
                  Still per-year but level-corrected for in-progress work.
- ``closeout``  — only projects with ``pct_compl == 1`` count toward totals.
                  Each completed project lands in exactly one year (the year
                  it closed). The most accounting-honest of the three.

Project Register rows are unchanged across modes — these functions only affect
the monthly / quarterly / totals rollups.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from app.services.parser import MONTH_TO_Q, MONTHS

ACCOUNTING_MODES = ("raw", "poc", "closeout")
DEFAULT_MODE = "raw"


@dataclass
class ProjectAggInput:
    job_no: str
    last_month: str | None
    pct_compl: float | None
    contract: float | None
    profit: float | None


def _to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce(project) -> ProjectAggInput:
    """Accept either ORM Project rows or dicts."""
    if isinstance(project, dict):
        return ProjectAggInput(
            job_no=str(project.get("job", project.get("job_no", ""))),
            last_month=project.get("last_month"),
            pct_compl=_to_float(project.get("pct_compl")),
            contract=_to_float(project.get("contract")),
            profit=_to_float(project.get("profit")),
        )
    return ProjectAggInput(
        job_no=str(getattr(project, "job_no", "")),
        last_month=getattr(project, "last_month", None),
        pct_compl=_to_float(getattr(project, "pct_compl", None)),
        contract=_to_float(getattr(project, "contract", None)),
        profit=_to_float(getattr(project, "profit", None)),
    )


def _factor(p: ProjectAggInput, mode: str) -> float:
    """Returns the multiplier applied to contract + profit for this project."""
    if mode == "poc":
        return p.pct_compl if p.pct_compl is not None else 0.0
    if mode == "closeout":
        return 1.0 if (p.pct_compl is not None and p.pct_compl >= 0.99) else 0.0
    return 1.0  # raw


def aggregate(
    projects: Iterable,
    *,
    mode: str = DEFAULT_MODE,
    overhead_by_month: dict[str, float] | None = None,
) -> tuple[list[dict], list[dict], dict]:
    """Return ``(monthly, quarterly, totals)`` computed from ``projects`` under
    the requested accounting mode."""
    if mode not in ACCOUNTING_MODES:
        raise ValueError(f"unknown accounting mode: {mode}")

    oh = overhead_by_month or {}
    gp_by_month: dict[str, float] = {m: 0.0 for m in MONTHS}
    sales_by_q: dict[str, float] = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
    gp_by_q: dict[str, float] = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}

    for raw in projects:
        p = _coerce(raw)
        factor = _factor(p, mode)
        if factor == 0:
            continue
        contract = (p.contract or 0) * factor
        profit = (p.profit or 0) * factor
        month = p.last_month
        if month and month in gp_by_month:
            gp_by_month[month] += profit
        if month and month in MONTH_TO_Q:
            q = MONTH_TO_Q[month]
            sales_by_q[q] += contract
            gp_by_q[q] += profit

    monthly: list[dict] = []
    for m in MONTHS:
        oh_m = oh.get(m, 0.0)
        gp = gp_by_month[m]
        monthly.append(
            {"month": m, "gross_profit": gp, "overhead": oh_m, "net_profit": gp - oh_m}
        )

    quarterly: list[dict] = []
    for q in ("Q1", "Q2", "Q3", "Q4"):
        sales = sales_by_q[q]
        gp = gp_by_q[q]
        q_oh = sum(oh.get(m, 0.0) for m, qq in MONTH_TO_Q.items() if qq == q)
        net = gp - q_oh
        quarterly.append(
            {
                "quarter": q,
                "sales": sales,
                "gross_profit": gp,
                "gross_pct": (gp / sales) if sales else 0,
                "overhead": q_oh,
                "overhead_pct": (q_oh / sales) if sales else 0,
                "net_profit": net,
                "net_pct": (net / sales) if sales else 0,
            }
        )

    sales = sum(q["sales"] for q in quarterly)
    gp = sum(q["gross_profit"] for q in quarterly)
    oh_total = sum(q["overhead"] for q in quarterly)
    net = gp - oh_total
    totals = {
        "sales": sales,
        "gross_profit": gp,
        "gross_pct": (gp / sales) if sales else 0,
        "overhead": oh_total,
        "overhead_pct": (oh_total / sales) if sales else 0,
        "net_profit": net,
        "net_pct": (net / sales) if sales else 0,
    }
    return monthly, quarterly, totals
