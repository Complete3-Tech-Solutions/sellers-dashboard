from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class YearsOut(BaseModel):
    years: list[int]
    default: int | None = None


class DashboardOut(BaseModel):
    year: int
    accounting: str = "raw"
    projects: list[dict[str, Any]]
    monthly: list[dict[str, Any]]
    quarterly: list[dict[str, Any]]
    overhead_detail: list[dict[str, Any]]
    totals: dict[str, Any]


class ProjectYearRow(BaseModel):
    fiscal_year: int
    last_month: str | None = None
    pct_compl: float | None = None
    contract: float | None = None
    cost: float | None = None
    profit: float | None = None
    profit_pct: float | None = None
    invoiced: float | None = None
    pmt_recd: float | None = None


class ProjectLifetimeOut(BaseModel):
    job_no: str
    name: str
    first_year: int
    last_year: int
    years: list[ProjectYearRow]
