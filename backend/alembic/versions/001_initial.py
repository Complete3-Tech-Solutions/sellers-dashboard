"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-19

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "001"
down_revision = None
branch_labels = None
depends_on = None


RLS_TABLES = (
    "projects",
    "monthly_metrics",
    "quarterly_metrics",
    "overhead_detail",
    "snapshots",
    "snapshot_files",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("plan", sa.Text(), nullable=False, server_default="trial"),
        sa.Column("logo_r2_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="member"),
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_email_per_tenant"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("issued_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False, unique=True),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("ip_allowlist", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("machine_fingerprint", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_ip", postgresql.INET(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_id", "api_keys", ["key_id"])

    op.create_table(
        "snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("file_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("committed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("parsed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_table(
        "snapshot_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("snapshots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("r2_key", sa.Text(), nullable=False),
        sa.Column("uploaded_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "filename", name="uq_snapfile"),
    )

    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("job_no", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("pct_compl", sa.Numeric(5, 4), nullable=True),
        sa.Column("contract", sa.Numeric(14, 2), nullable=True),
        sa.Column("cost", sa.Numeric(14, 2), nullable=True),
        sa.Column("profit", sa.Numeric(14, 2), nullable=True),
        sa.Column("profit_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("invoiced", sa.Numeric(14, 2), nullable=True),
        sa.Column("pmt_recd", sa.Numeric(14, 2), nullable=True),
        sa.Column("last_month", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "fiscal_year", "job_no", name="uq_project_per_year"),
    )

    op.create_table(
        "monthly_metrics",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fiscal_year", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Text(), primary_key=True),
        sa.Column("gross_profit", sa.Numeric(14, 2), nullable=True),
        sa.Column("overhead", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_profit", sa.Numeric(14, 2), nullable=True),
    )

    op.create_table(
        "quarterly_metrics",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fiscal_year", sa.Integer(), primary_key=True),
        sa.Column("quarter", sa.Text(), primary_key=True),
        sa.Column("sales", sa.Numeric(14, 2), nullable=True),
        sa.Column("gross_profit", sa.Numeric(14, 2), nullable=True),
        sa.Column("gross_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("overhead", sa.Numeric(14, 2), nullable=True),
        sa.Column("overhead_pct", sa.Numeric(7, 4), nullable=True),
        sa.Column("net_profit", sa.Numeric(14, 2), nullable=True),
        sa.Column("net_pct", sa.Numeric(7, 4), nullable=True),
    )

    op.create_table(
        "overhead_detail",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fiscal_year", sa.Integer(), primary_key=True),
        sa.Column("month", sa.Text(), primary_key=True),
        sa.Column("overhead", sa.Numeric(14, 2), nullable=True),
        sa.Column("computers", sa.Numeric(14, 2), nullable=True),
        sa.Column("furniture", sa.Numeric(14, 2), nullable=True),
        sa.Column("total", sa.Numeric(14, 2), nullable=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_audit_tenant_at", "audit_log", ["tenant_id", sa.text("at DESC")])
    op.create_index("ix_projects_tenant_year", "projects", ["tenant_id", "fiscal_year"])
    op.create_index("ix_snapshots_tenant_started", "snapshots", ["tenant_id", sa.text("started_at DESC")])

    # Row-level security
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid)
            """
        )


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_snapshots_tenant_started", table_name="snapshots")
    op.drop_index("ix_projects_tenant_year", table_name="projects")
    op.drop_index("ix_audit_tenant_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("overhead_detail")
    op.drop_table("quarterly_metrics")
    op.drop_table("monthly_metrics")
    op.drop_table("projects")
    op.drop_table("snapshot_files")
    op.drop_table("snapshots")
    op.drop_index("ix_api_keys_key_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("tenants")
