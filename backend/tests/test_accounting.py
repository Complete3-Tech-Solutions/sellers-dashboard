from __future__ import annotations

from app.services.accounting import aggregate


def _proj(**kw):
    base = {"job": "X", "name": "n", "last_month": "January", "pct_compl": 1.0,
            "contract": 100.0, "profit": 20.0}
    base.update(kw)
    return base


def test_raw_mode_sums_full_contract_and_profit():
    projects = [
        _proj(job="A", last_month="January", contract=1000, profit=100, pct_compl=0.25),
        _proj(job="B", last_month="June", contract=500, profit=50, pct_compl=1.0),
    ]
    monthly, quarterly, totals = aggregate(projects, mode="raw")
    assert totals["sales"] == 1500
    assert totals["gross_profit"] == 150
    # January (Q1) gets the full $1000 even though it's only 25% done
    assert quarterly[0]["sales"] == 1000
    assert quarterly[1]["sales"] == 500   # Q2 = June


def test_poc_mode_scales_by_completion():
    projects = [
        _proj(job="A", last_month="January", contract=1000, profit=100, pct_compl=0.25),
        _proj(job="B", last_month="June", contract=500, profit=50, pct_compl=1.0),
    ]
    monthly, quarterly, totals = aggregate(projects, mode="poc")
    # A contributes 1000 * 0.25 = 250; B contributes 500 * 1.0 = 500
    assert totals["sales"] == 750
    assert totals["gross_profit"] == 125   # 100*0.25 + 50*1
    assert quarterly[0]["sales"] == 250
    assert quarterly[1]["sales"] == 500


def test_closeout_mode_excludes_in_progress():
    projects = [
        _proj(job="A", last_month="January", contract=1000, profit=100, pct_compl=0.25),
        _proj(job="B", last_month="June", contract=500, profit=50, pct_compl=1.0),
    ]
    monthly, quarterly, totals = aggregate(projects, mode="closeout")
    # Only B (fully complete) counts
    assert totals["sales"] == 500
    assert totals["gross_profit"] == 50
    assert quarterly[0]["sales"] == 0   # A excluded
    assert quarterly[1]["sales"] == 500


def test_overhead_passes_through_in_all_modes():
    projects = [_proj(job="A", last_month="January", contract=1000, profit=100, pct_compl=1)]
    overhead = {"January": 30, "February": 50}
    for mode in ("raw", "poc", "closeout"):
        monthly, quarterly, totals = aggregate(projects, mode=mode, overhead_by_month=overhead)
        jan = next(m for m in monthly if m["month"] == "January")
        feb = next(m for m in monthly if m["month"] == "February")
        assert jan["overhead"] == 30
        assert feb["overhead"] == 50
        # Net = gross - overhead per month
        assert jan["net_profit"] == jan["gross_profit"] - 30


def test_unknown_mode_raises():
    import pytest
    with pytest.raises(ValueError):
        aggregate([], mode="bogus")


def test_handles_dict_or_orm_like_input():
    """The aggregator accepts either dicts (from cached JSON) or ORM-row-like objects."""
    class FakeORM:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)
    p1 = FakeORM(job_no="A", last_month="January", pct_compl=1.0, contract=100, profit=10)
    p2 = {"job_no": "B", "last_month": "June", "pct_compl": 0.5, "contract": 200, "profit": 40}
    _, _, totals = aggregate([p1, p2], mode="poc")
    assert totals["sales"] == 100 + 200 * 0.5  # 200
    assert totals["gross_profit"] == 10 + 40 * 0.5  # 30
