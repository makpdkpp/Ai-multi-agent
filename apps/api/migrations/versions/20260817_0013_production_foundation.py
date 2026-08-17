"""Add source indexing, handoff, widget sessions and budget alerts."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260817_0013"
down_revision: str | None = "20260817_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def _tenant(table: str) -> None:
    expression = (
        "department_id = NULLIF(current_setting('app.department_id', true), '')::uuid "
        "OR current_setting('app.system_role', true) = 'super_admin'"
    )
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} USING ({expression}) WITH CHECK ({expression})"
    )


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    now = sa.text("now()")
    op.create_table(
        "source_chunks",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("department_id", uuid, sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_source_id", uuid, sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_file_id", uuid, sa.ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint("source_file_id", "chunk_index", name="uq_source_chunks_file_index"),
    )
    op.create_index("ix_source_chunks_source_content", "source_chunks", ["data_source_id", "source_file_id"])

    op.create_table(
        "handoff_cases",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("department_id", uuid, sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", uuid, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", uuid, sa.ForeignKey("chat_conversations.id", ondelete="CASCADE")),
        sa.Column("requester_user_id", uuid, sa.ForeignKey("users.id")),
        sa.Column("requester_contact", sa.String(255)),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(20), nullable=False, server_default="normal"),
        sa.Column("subject", sa.String(255)),
        sa.Column("reason", sa.Text()),
        sa.Column("assigned_to", uuid, sa.ForeignKey("users.id")),
        sa.Column("sla_due_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.CheckConstraint("status IN ('open','assigned','pending','resolved','closed')", name="ck_handoff_status"),
        sa.CheckConstraint("priority IN ('low','normal','high','urgent')", name="ck_handoff_priority"),
    )
    op.create_index("ix_handoff_cases_department_status", "handoff_cases", ["department_id", "status", "created_at"])
    op.create_table(
        "handoff_case_messages",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("case_id", uuid, sa.ForeignKey("handoff_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sender_user_id", uuid, sa.ForeignKey("users.id")),
        sa.Column("sender_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_handoff_messages_case_created", "handoff_case_messages", ["case_id", "created_at"])

    op.create_table(
        "widget_sessions",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("department_id", uuid, sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", uuid, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("origin", sa.String(255)),
        sa.Column("contact", sa.String(255)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_table(
        "budget_alerts",
        sa.Column("id", uuid, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("department_id", uuid, sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_id", uuid, sa.ForeignKey("department_budgets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_key", sa.String(30), nullable=False),
        sa.Column("threshold_percent", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint("budget_id", "period_key", "threshold_percent", name="uq_budget_alert_threshold"),
    )
    for table in ("source_chunks", "handoff_cases", "handoff_case_messages", "widget_sessions", "budget_alerts"):
        _tenant(table)
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO "{_role()}"')


def downgrade() -> None:
    op.drop_table("budget_alerts")
    op.drop_table("widget_sessions")
    op.drop_table("handoff_case_messages")
    op.drop_table("handoff_cases")
    op.drop_table("source_chunks")
