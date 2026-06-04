"""RQ job: parse a committed snapshot into structured tables."""
from __future__ import annotations

import logging
import pathlib
import tempfile
import uuid
from datetime import UTC, datetime

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.models import (
    MonthlyMetric,
    OverheadDetail,
    Project,
    QuarterlyMetric,
    Snapshot,
    SnapshotFile,
)
from app.services import parser as parser_mod
from app.services import storage
from app.settings import settings

log = logging.getLogger(__name__)


def _sync_engine():
    """RQ runs sync — use a sync engine for the worker."""
    url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    if "postgresql://" not in url and "psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return create_engine(url, future=True)


def _download_to(tmpdir: pathlib.Path, files: list[SnapshotFile]) -> pathlib.Path:
    for f in files:
        dest = tmpdir / f.filename
        dest.write_bytes(storage.get_bytes(f.r2_key))
    return tmpdir


def parse_snapshot_job(snapshot_id_str: str) -> dict:
    snapshot_id = uuid.UUID(snapshot_id_str)
    engine = _sync_engine()
    with Session(engine, expire_on_commit=False) as session:
        snap = session.get(Snapshot, snapshot_id)
        if snap is None:
            return {"ok": False, "error": "snapshot_not_found"}
        if snap.status not in ("committed", "failed"):
            return {"ok": False, "error": f"unexpected_status:{snap.status}"}

        files = session.execute(
            select(SnapshotFile).where(SnapshotFile.snapshot_id == snapshot_id)
        ).scalars().all()

        try:
            with tempfile.TemporaryDirectory(prefix="scc-parse-") as td:
                tmpdir = pathlib.Path(td)
                _download_to(tmpdir, files)

                # Snapshots can carry files for multiple years (typical for the
                # first backfill upload). Parse and apply each year independently.
                parsed_years = parser_mod.parse_folder_all_years(tmpdir)
                tenant_id = snap.tenant_id
                total_projects = 0
                applied_years: list[int] = []

                for parsed in parsed_years:
                    year = parsed.fiscal_year
                    if not parsed.projects and not parsed.monthly:
                        log.info("year %s: no data, skipping", year)
                        continue

                    session.execute(
                        delete(Project).where(
                            Project.tenant_id == tenant_id, Project.fiscal_year == year
                        )
                    )
                    session.execute(
                        delete(MonthlyMetric).where(
                            MonthlyMetric.tenant_id == tenant_id,
                            MonthlyMetric.fiscal_year == year,
                        )
                    )
                    session.execute(
                        delete(QuarterlyMetric).where(
                            QuarterlyMetric.tenant_id == tenant_id,
                            QuarterlyMetric.fiscal_year == year,
                        )
                    )
                    session.execute(
                        delete(OverheadDetail).where(
                            OverheadDetail.tenant_id == tenant_id,
                            OverheadDetail.fiscal_year == year,
                        )
                    )

                    session.add_all(
                        Project(
                            tenant_id=tenant_id, fiscal_year=year,
                            job_no=p.job_no, name=p.name,
                            pct_compl=p.pct_compl, contract=p.contract,
                            cost=p.cost, profit=p.profit, profit_pct=p.profit_pct,
                            invoiced=p.invoiced, pmt_recd=p.pmt_recd,
                            last_month=p.last_month,
                        )
                        for p in parsed.projects
                    )
                    session.add_all(
                        MonthlyMetric(
                            tenant_id=tenant_id, fiscal_year=year, month=m.month,
                            gross_profit=m.gross_profit, overhead=m.overhead,
                            net_profit=m.net_profit,
                        )
                        for m in parsed.monthly
                    )
                    session.add_all(
                        QuarterlyMetric(
                            tenant_id=tenant_id, fiscal_year=year, quarter=q.quarter,
                            sales=q.sales, gross_profit=q.gross_profit,
                            gross_pct=q.gross_pct, overhead=q.overhead,
                            overhead_pct=q.overhead_pct, net_profit=q.net_profit,
                            net_pct=q.net_pct,
                        )
                        for q in parsed.quarterly
                    )
                    session.add_all(
                        OverheadDetail(
                            tenant_id=tenant_id, fiscal_year=year, month=o.month,
                            overhead=o.overhead, computers=o.computers,
                            furniture=o.furniture, total=o.total,
                        )
                        for o in parsed.overhead_detail
                    )
                    total_projects += len(parsed.projects)
                    applied_years.append(year)

                snap.status = "parsed"
                snap.parsed_at = datetime.now(tz=UTC)
                snap.error = None
                session.commit()

                # Cache invalidation (best-effort; sync redis lib here)
                try:
                    import redis

                    r = redis.from_url(settings.redis_url)
                    for k in r.scan_iter(f"dashboard:{tenant_id}:*"):
                        r.delete(k)
                except Exception:
                    pass

                return {
                    "ok": True,
                    "years": applied_years,
                    "projects": total_projects,
                }

        except Exception as exc:
            log.exception("parse failed")
            snap.status = "failed"
            snap.error = str(exc)[:2000]
            session.commit()
            return {"ok": False, "error": snap.error}
