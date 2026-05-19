from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class YearsOut(BaseModel):
    years: list[int]
    default: int | None = None


class DashboardOut(BaseModel):
    year: int
    projects: list[dict[str, Any]]
    monthly: list[dict[str, Any]]
    quarterly: list[dict[str, Any]]
    overhead_detail: list[dict[str, Any]]
    totals: dict[str, Any]
