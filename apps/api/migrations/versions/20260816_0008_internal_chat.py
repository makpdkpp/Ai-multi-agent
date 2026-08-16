"""Add internal chat conversations and messages.

Revision ID: 20260816_0008
Revises: 20260816_0007
Create Date: 2026-08-16
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0008"
down_revision: str | None = "20260816_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
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
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("title", sa.String(200), nullable=False, server_default="New chat"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_chat_conversations_status"),
    )
    op.create_index(
        "ix_chat_conversations_department_updated",
        "chat_conversations",
        ["department_id", "updated_at"],
    )
    op.create_index(
        "ix_chat_conversations_created_by_updated",
        "chat_conversations",
        ["created_by", "updated_at"],
    )

    op.create_table(
        "chat_messages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
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
        sa.Column("sender_type", sa.String(20), nullable=False),
        sa.Column("sender_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("usage_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_usage_events.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("sender_type IN ('user', 'assistant', 'system')", name="ck_chat_messages_sender"),
    )
    op.create_index("ix_chat_messages_conversation_created", "chat_messages", ["conversation_id", "created_at"])
    op.create_index("ix_chat_messages_department_created", "chat_messages", ["department_id", "created_at"])

    user_id = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    super_admin = "current_setting('app.system_role', true) = 'super_admin'"
    department_manager = (
        "EXISTS (SELECT 1 FROM department_memberships membership "
        "WHERE membership.department_id = chat_conversations.department_id "
        f"AND membership.user_id = {user_id} "
        "AND membership.status = 'active' "
        "AND membership.role IN ('department_admin', 'agent_manager'))"
    )
    active_member = (
        "EXISTS (SELECT 1 FROM department_memberships membership "
        "WHERE membership.department_id = chat_conversations.department_id "
        f"AND membership.user_id = {user_id} "
        "AND membership.status = 'active')"
    )
    conversation_read = f"{super_admin} OR chat_conversations.created_by = {user_id} OR {department_manager}"
    conversation_write = f"{super_admin} OR (chat_conversations.created_by = {user_id} AND {active_member})"
    message_read = (
        "EXISTS (SELECT 1 FROM chat_conversations "
        "WHERE chat_conversations.id = chat_messages.conversation_id "
        f"AND ({conversation_read}))"
    )
    message_write = (
        "EXISTS (SELECT 1 FROM chat_conversations "
        "WHERE chat_conversations.id = chat_messages.conversation_id "
        f"AND ({conversation_write}))"
    )

    for table in ("chat_conversations", "chat_messages"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        "CREATE POLICY chat_conversations_select ON chat_conversations FOR SELECT "
        f"USING ({conversation_read})"
    )
    op.execute(
        "CREATE POLICY chat_conversations_write ON chat_conversations FOR ALL "
        f"USING ({conversation_write}) WITH CHECK ({conversation_write})"
    )
    op.execute(
        "CREATE POLICY chat_messages_select ON chat_messages FOR SELECT "
        f"USING ({message_read})"
    )
    op.execute(
        "CREATE POLICY chat_messages_write ON chat_messages FOR ALL "
        f"USING ({message_write}) WITH CHECK ({message_write})"
    )

    app_role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_conversations")
