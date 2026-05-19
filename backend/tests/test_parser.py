from __future__ import annotations

import pathlib

from openpyxl import Workbook

from app.services import parser


def _write_profitability(tmp: pathlib.Path) -> pathlib.Path:
    path = tmp / "Profitability_2024.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "2024"
    ws.append(["FY 2024", None, None, None, None, None, None])  # title row
    ws.append([])
    ws.append(["Job #", "Project Name", "% Compl", "Contract", "Cost", "Profit", "Margin", "Invoiced", "Pmt Recd", "Last Month"])
    ws.append([101, "Foo", 1.0, 10000, 7000, 3000, 0.30, 10000, 10000, "January"])
    ws.append([102, "Bar", 0.5, 50000, 25000, 25000, 0.50, 25000, 0, "March"])
    wb.save(path)
    return path


def _write_overhead(tmp: pathlib.Path) -> pathlib.Path:
    path = tmp / "Overhead_2024.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Month", "Overhead", "Computers", "Furniture", "Total"])
    ws.append(["January", 1000, 0, 0, 1000])
    ws.append(["February", 1500, 200, 0, 1700])
    ws.append(["March", 800, 0, 100, 900])
    wb.save(path)
    return path


def test_parse_folder(tmp_path: pathlib.Path):
    _write_profitability(tmp_path)
    _write_overhead(tmp_path)
    snap = parser.parse_folder(tmp_path)
    assert snap.fiscal_year == 2024
    assert len(snap.projects) == 2
    assert snap.projects[0].job_no == "101"
    assert snap.projects[0].profit == 3000
    assert any(o.month == "January" for o in snap.overhead_detail)
    assert len(snap.monthly) == 12
    assert len(snap.quarterly) == 4
    # Totals should aggregate quarterly
    assert snap.totals.sales > 0


def test_to_number_currency_handling():
    assert parser.to_number("$1,234.56") == 1234.56
    assert parser.to_number("(500)") == -500
    assert parser.to_number("25%") == 0.25
    assert parser.to_number("") is None
    assert parser.to_number("INVOICED") is None
