"""Add data sources and Excel source files.

Revision ID: 20260816_0010
Revises: 20260816_0009
Create Date: 2026-08-16
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0010"
down_revision: str | None = "20260816_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("secret_ref", sa.Text()),
        sa.Column("connection_config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("allowed_schema", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("source_type IN ('mysql', 'excel', 'pdf')", name="ck_data_sources_source_type"),
        sa.CheckConstraint(
            "status IN ('draft', 'validating', 'ready', 'error', 'disabled')",
            name="ck_data_sources_status",
        ),
    )
    op.create_index("ix_data_sources_department_type_status", "data_sources", ["department_id", "source_type", "status"])

    op.create_table(
        "source_files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "data_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="uploaded"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("processing_error", sa.Text()),
        sa.Column("uploaded_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed', 'quarantined')",
            name="ck_source_files_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_source_files_version"),
    )
    op.create_index("ix_source_files_data_source_version", "source_files", ["data_source_id", "version"])
    op.create_index("ix_source_files_department_status", "source_files", ["department_id", "status"])

    op.create_table(
        "agent_data_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "department_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "data_source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("access_scope", sa.String(20), nullable=False, server_default="internal_only"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "access_scope IN ('internal_only', 'public_allowed')",
            name="ck_agent_data_sources_access_scope",
        ),
        sa.UniqueConstraint("agent_id", "data_source_id", name="uq_agent_data_sources_agent_source"),
    )
    op.create_index("ix_agent_data_sources_agent_enabled", "agent_data_sources", ["agent_id", "enabled"])
    op.create_index("ix_agent_data_sources_department", "agent_data_sources", ["department_id"])

    tenant_expression = (
        "department_id = NULLIF(current_setting('app.department_id', true), '')::uuid "
        "OR current_setting('app.system_role', true) = 'super_admin'"
    )
    for table in ("data_sources", "source_files", "agent_data_sources"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
        )

    app_role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE data_sources TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE source_files TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE agent_data_sources TO "{app_role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("agent_data_sources")
    op.drop_table("source_files")
    op.drop_table("data_sources")
