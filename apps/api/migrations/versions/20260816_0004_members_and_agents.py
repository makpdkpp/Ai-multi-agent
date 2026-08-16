"""Add department member management and agent configuration tables.

Revision ID: 20260816_0004
Revises: 20260816_0003
Create Date: 2026-08-16
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0004"
down_revision: str | None = "20260816_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    op.create_table(
        "agents",
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
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("default_language", sa.String(10), nullable=False, server_default="th"),
        sa.Column("handoff_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("confidence_threshold", sa.Numeric(5, 4), nullable=False, server_default="0.6000"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("slug ~ '^[a-z][a-z0-9-]{1,79}$'", name="ck_agents_slug"),
        sa.CheckConstraint("status IN ('draft', 'active', 'paused', 'disabled')", name="ck_agents_status"),
        sa.CheckConstraint(
            "confidence_threshold >= 0 AND confidence_threshold <= 1",
            name="ck_agents_confidence_threshold",
        ),
        sa.UniqueConstraint("department_id", "slug", name="uq_agents_department_slug"),
    )
    op.create_index("ix_agents_department_status", "agents", ["department_id", "status"])

    op.create_table(
        "agent_prompt_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("response_style", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("version >= 1", name="ck_agent_prompt_versions_version"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_prompt_versions_agent_version"),
    )
    op.create_index(
        "ix_agent_prompt_versions_agent_active",
        "agent_prompt_versions",
        ["agent_id", "is_active"],
    )

    op.create_table(
        "agent_permissions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("allow_anonymous", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "channel IN ('internal_chat', 'public_widget', 'email')",
            name="ck_agent_permissions_channel",
        ),
        sa.UniqueConstraint("agent_id", "channel", name="uq_agent_permissions_agent_channel"),
    )

    op.create_table(
        "agent_llm_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_providers.id")),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_models.id")),
        sa.Column("model_key", sa.String(200), nullable=False),
        sa.Column("temperature", sa.Numeric(4, 2), nullable=False, server_default="0.20"),
        sa.Column("top_p", sa.Numeric(4, 2), nullable=False, server_default="1.00"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("temperature >= 0 AND temperature <= 2", name="ck_agent_llm_temperature"),
        sa.CheckConstraint("top_p > 0 AND top_p <= 1", name="ck_agent_llm_top_p"),
        sa.CheckConstraint(
            "max_output_tokens BETWEEN 1 AND 200000",
            name="ck_agent_llm_max_output_tokens",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_agent_llm_status"),
    )
    op.create_index("ix_agent_llm_configs_agent_status", "agent_llm_configs", ["agent_id", "status"])

    for table in ("agents",):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = (
            "department_id = NULLIF(current_setting('app.department_id', true), '')::uuid "
            "OR current_setting('app.system_role', true) = 'super_admin'"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )

    for table in ("agent_prompt_versions", "agent_permissions", "agent_llm_configs"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        expression = (
            "EXISTS (SELECT 1 FROM agents "
            f"WHERE agents.id = {table}.agent_id "
            "AND (agents.department_id = NULLIF(current_setting('app.department_id', true), '')::uuid "
            "OR current_setting('app.system_role', true) = 'super_admin'))"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )

    app_role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("agent_llm_configs")
    op.drop_table("agent_permissions")
    op.drop_table("agent_prompt_versions")
    op.drop_table("agents")
