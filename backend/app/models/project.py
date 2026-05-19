from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fiscal_year", "job_no", name="uq_project_per_year"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    job_no: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    pct_compl: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    contract: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    profit_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    invoiced: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    pmt_recd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    last_month: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MonthlyMetric(Base):
    __tablename__ = "monthly_metrics"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String, primary_key=True)
    gross_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    overhead: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)


class QuarterlyMetric(Base):
    __tablename__ = "quarterly_metrics"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    quarter: Mapped[str] = mapped_column(String, primary_key=True)
    sales: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    gross_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    gross_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    overhead: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    overhead_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)
    net_profit: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    net_pct: Mapped[Decimal | None] = mapped_column(Numeric(7, 4), nullable=True)


class OverheadDetail(Base):
    __tablename__ = "overhead_detail"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    month: Mapped[str] = mapped_column(String, primary_key=True)
    overhead: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    computers: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    furniture: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
