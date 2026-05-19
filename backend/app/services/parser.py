"""Excel parser for SCC's job-cost workbooks.

The parser is deterministic and side-effect-free. It scans each workbook for a
header row (case-insensitive match on the canonical column names), then pulls
data rows beneath it. Currency strings are normalized to floats. Empty rows
between sections are tolerated.
"""
from __future__ import annotations

import logging
import pathlib
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from openpyxl import load_workbook

log = logging.getLogger(__name__)

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
MONTH_TO_Q = {
    "January": "Q1", "February": "Q1", "March": "Q1",
    "April": "Q2", "May": "Q2", "June": "Q2",
    "July": "Q3", "August": "Q3", "September": "Q3",
    "October": "Q4", "November": "Q4", "December": "Q4",
}


@dataclass
class ProjectRow:
    job_no: str
    name: str
    pct_compl: float | None = None
    contract: float | None = None
    cost: float | None = None
    profit: float | None = None
    profit_pct: float | None = None
    invoiced: float | None = None
    pmt_recd: float | None = None
    last_month: str | None = None


@dataclass
class MonthlyRow:
    month: str
    gross_profit: float | None = None
    overhead: float | None = None
    net_profit: float | None = None


@dataclass
class QuarterlyRow:
    quarter: str
    sales: float | None = None
    gross_profit: float | None = None
    gross_pct: float | None = None
    overhead: float | None = None
    overhead_pct: float | None = None
    net_profit: float | None = None
    net_pct: float | None = None


@dataclass
class OverheadRow:
    month: str
    overhead: float | None = None
    computers: float | None = None
    furniture: float | None = None
    total: float | None = None


@dataclass
class TotalsRow:
    sales: float = 0.0
    gross_profit: float = 0.0
    gross_pct: float = 0.0
    overhead: float = 0.0
    overhead_pct: float = 0.0
    net_profit: float = 0.0
    net_pct: float = 0.0


@dataclass
class ParsedSnapshot:
    fiscal_year: int
    projects: list[ProjectRow] = field(default_factory=list)
    monthly: list[MonthlyRow] = field(default_factory=list)
    quarterly: list[QuarterlyRow] = field(default_factory=list)
    overhead_detail: list[OverheadRow] = field(default_factory=list)
    totals: TotalsRow = field(default_factory=TotalsRow)


_NUMBER_RE = re.compile(r"^-?\$?\(?[\d,]*\.?\d+\)?%?$")


def to_number(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    s = str(v).strip()
    if not s or s in {"-", "—"}:
        return None
    # Sentinel values used in the source spreadsheet (kept for backward compat with raw exports)
    if s.upper() in {"INVOICED", "PMT RECD"}:
        return None
    neg = s.startswith("(") and s.endswith(")")
    s2 = s.strip("()").replace("$", "").replace(",", "").strip()
    pct = s2.endswith("%")
    s2 = s2.rstrip("%").strip()
    try:
        n = float(s2)
    except ValueError:
        return None
    if neg:
        n = -n
    if pct:
        n = n / 100.0
    return n


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


# Canonical header tokens we look for (normalized)
PROJECT_HEADERS = {
    "job": ("jobno", "job", "job#"),
    "name": ("name", "projectname", "project"),
    "pct_compl": ("pctcompl", "complete", "compl"),
    "contract": ("contract", "contractvalue", "contracttotal"),
    "cost": ("cost", "totalcost"),
    "profit": ("profit", "grossprofit"),
    "profit_pct": ("margin", "profitpct", "profitmargin"),
    "invoiced": ("invoiced",),
    "pmt_recd": ("pmtrecd", "paymentreceived", "paid"),
    "last_month": ("lastmonth", "month"),
}
MONTHLY_HEADERS = {
    "month": ("month",),
    "gross_profit": ("grossprofit", "gross"),
    "overhead": ("overhead",),
    "net_profit": ("netprofit", "net"),
}
OVERHEAD_HEADERS = {
    "month": ("month",),
    "overhead": ("overhead",),
    "computers": ("computers",),
    "furniture": ("furniture",),
    "total": ("total",),
}


def _find_header(rows: list[list[Any]], schema: dict[str, tuple[str, ...]]) -> tuple[int, dict[str, int]] | None:
    """Return (row_index, {field: col_idx}) for the first row that contains the required tokens."""
    required = {"job", "name"} if schema is PROJECT_HEADERS else {"month"}
    for i, row in enumerate(rows):
        normalized = [_norm(c) for c in row]
        mapping: dict[str, int] = {}
        for field_name, tokens in schema.items():
            for tok in tokens:
                if tok in normalized:
                    mapping[field_name] = normalized.index(tok)
                    break
        if required <= set(mapping.keys()):
            return i, mapping
    return None


def _year_from_filename(path: pathlib.Path) -> int | None:
    m = re.search(r"(20\d{2})", path.name)
    return int(m.group(1)) if m else None


def parse_profitability(rows: list[list[Any]]) -> list[ProjectRow]:
    located = _find_header(rows, PROJECT_HEADERS)
    if not located:
        log.warning("no project header found")
        return []
    start, cols = located
    out: list[ProjectRow] = []
    for r in rows[start + 1 :]:
        job_v = r[cols["job"]] if cols.get("job") is not None and cols["job"] < len(r) else None
        name_v = r[cols["name"]] if cols.get("name") is not None and cols["name"] < len(r) else None
        if not job_v or not name_v:
            continue
        try:
            row = ProjectRow(
                job_no=str(job_v).strip(),
                name=str(name_v).strip(),
                pct_compl=to_number(r[cols["pct_compl"]]) if "pct_compl" in cols and cols["pct_compl"] < len(r) else None,
                contract=to_number(r[cols["contract"]]) if "contract" in cols and cols["contract"] < len(r) else None,
                cost=to_number(r[cols["cost"]]) if "cost" in cols and cols["cost"] < len(r) else None,
                profit=to_number(r[cols["profit"]]) if "profit" in cols and cols["profit"] < len(r) else None,
                profit_pct=to_number(r[cols["profit_pct"]]) if "profit_pct" in cols and cols["profit_pct"] < len(r) else None,
                invoiced=to_number(r[cols["invoiced"]]) if "invoiced" in cols and cols["invoiced"] < len(r) else None,
                pmt_recd=to_number(r[cols["pmt_recd"]]) if "pmt_recd" in cols and cols["pmt_recd"] < len(r) else None,
                last_month=str(r[cols["last_month"]]).strip() if "last_month" in cols and cols["last_month"] < len(r) and r[cols["last_month"]] else None,
            )
            # Fill in derived fields where source omitted them
            if row.profit is None and row.contract is not None and row.cost is not None:
                row.profit = row.contract - row.cost
            if (
                row.profit_pct is None
                and row.profit is not None
                and row.contract not in (None, 0)
            ):
                row.profit_pct = row.profit / row.contract
            out.append(row)
        except Exception as exc:
            log.warning("skipping bad project row: %s", exc)
            continue
    return out


def parse_overhead(rows: list[list[Any]]) -> list[OverheadRow]:
    located = _find_header(rows, OVERHEAD_HEADERS)
    if not located:
        return []
    start, cols = located
    out: list[OverheadRow] = []
    for r in rows[start + 1 :]:
        month_v = r[cols["month"]] if "month" in cols and cols["month"] < len(r) else None
        if not month_v:
            continue
        month = str(month_v).strip()
        if month not in MONTHS:
            continue
        oh = to_number(r[cols["overhead"]]) if "overhead" in cols and cols["overhead"] < len(r) else None
        comp = to_number(r[cols["computers"]]) if "computers" in cols and cols["computers"] < len(r) else 0
        furn = to_number(r[cols["furniture"]]) if "furniture" in cols and cols["furniture"] < len(r) else 0
        total = to_number(r[cols["total"]]) if "total" in cols and cols["total"] < len(r) else None
        if total is None:
            total = (oh or 0) + (comp or 0) + (furn or 0)
        out.append(
            OverheadRow(
                month=month,
                overhead=oh,
                computers=comp,
                furniture=furn,
                total=total,
            )
        )
    return out


def compute_monthly_from_projects(
    projects: list[ProjectRow], overhead: list[OverheadRow]
) -> list[MonthlyRow]:
    oh_by_month = {o.month: (o.total or 0) for o in overhead}
    rows: list[MonthlyRow] = []
    # Gross profit by month from projects (using last_month as the booked-in period)
    gp_by_month: dict[str, float] = {m: 0.0 for m in MONTHS}
    for p in projects:
        if p.last_month and p.last_month in gp_by_month and p.profit is not None:
            gp_by_month[p.last_month] += float(p.profit)
    for m in MONTHS:
        gp = gp_by_month.get(m, 0.0)
        oh = oh_by_month.get(m, 0.0)
        rows.append(MonthlyRow(month=m, gross_profit=gp, overhead=oh, net_profit=gp - oh))
    return rows


def compute_quarterly_from_projects(
    projects: list[ProjectRow], monthly: list[MonthlyRow]
) -> list[QuarterlyRow]:
    monthly_by = {m.month: m for m in monthly}

    # Sales = sum of contracts whose last_month falls in that quarter (matches the source dashboard's
    # rollup of "revenue booked in that period"). If your shop accounts differently, adjust here.
    sales_by_q: dict[str, float] = {"Q1": 0, "Q2": 0, "Q3": 0, "Q4": 0}
    gp_by_q = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
    oh_by_q = {"Q1": 0.0, "Q2": 0.0, "Q3": 0.0, "Q4": 0.0}
    for p in projects:
        if p.last_month and p.last_month in MONTH_TO_Q:
            q = MONTH_TO_Q[p.last_month]
            if p.contract is not None:
                sales_by_q[q] += float(p.contract)
    for m in MONTHS:
        q = MONTH_TO_Q[m]
        mrow = monthly_by.get(m)
        if mrow:
            gp_by_q[q] += float(mrow.gross_profit or 0)
            oh_by_q[q] += float(mrow.overhead or 0)

    rows: list[QuarterlyRow] = []
    for q in ("Q1", "Q2", "Q3", "Q4"):
        sales = sales_by_q[q]
        gp = gp_by_q[q]
        oh = oh_by_q[q]
        net = gp - oh
        rows.append(
            QuarterlyRow(
                quarter=q,
                sales=sales,
                gross_profit=gp,
                gross_pct=(gp / sales) if sales else 0,
                overhead=oh,
                overhead_pct=(oh / sales) if sales else 0,
                net_profit=net,
                net_pct=(net / sales) if sales else 0,
            )
        )
    return rows


def compute_totals(quarterly: list[QuarterlyRow]) -> TotalsRow:
    sales = sum((q.sales or 0) for q in quarterly)
    gp = sum((q.gross_profit or 0) for q in quarterly)
    oh = sum((q.overhead or 0) for q in quarterly)
    net = gp - oh
    return TotalsRow(
        sales=sales,
        gross_profit=gp,
        gross_pct=(gp / sales) if sales else 0,
        overhead=oh,
        overhead_pct=(oh / sales) if sales else 0,
        net_profit=net,
        net_pct=(net / sales) if sales else 0,
    )


def _all_rows(path: pathlib.Path) -> list[list[Any]]:
    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    out: list[list[Any]] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            out.append(list(row))
    wb.close()
    return out


def parse_folder(folder: pathlib.Path) -> ParsedSnapshot:
    """Parse all .xlsx files in `folder`. Year is inferred from filenames."""
    fy: int | None = None
    project_files: list[pathlib.Path] = []
    overhead_files: list[pathlib.Path] = []

    for p in sorted(folder.glob("*.xlsx")):
        if p.name.startswith("~$"):
            continue
        lower = p.name.lower()
        if fy is None:
            fy = _year_from_filename(p)
        if "overhead" in lower:
            overhead_files.append(p)
        else:
            project_files.append(p)

    if fy is None:
        from datetime import date

        fy = date.today().year

    snap = ParsedSnapshot(fiscal_year=fy)
    for pf in project_files:
        rows = _all_rows(pf)
        snap.projects.extend(parse_profitability(rows))
    for of in overhead_files:
        rows = _all_rows(of)
        snap.overhead_detail.extend(parse_overhead(rows))

    snap.monthly = compute_monthly_from_projects(snap.projects, snap.overhead_detail)
    snap.quarterly = compute_quarterly_from_projects(snap.projects, snap.monthly)
    snap.totals = compute_totals(snap.quarterly)
    return snap
