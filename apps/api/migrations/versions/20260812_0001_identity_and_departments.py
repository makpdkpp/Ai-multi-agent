"""Create identity and department foundation.

Revision ID: 20260812_0001
Revises:
Create Date: 2026-08-12
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260812_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("system_role", sa.String(30), nullable=False, server_default="standard_user"),
        sa.Column("status", sa.String(20), nullable=False, server_default="invited"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("system_role IN ('super_admin', 'standard_user')", name="ck_users_system_role"),
        sa.CheckConstraint("status IN ('active', 'disabled', 'invited')", name="ck_users_status"),
    )

    op.create_table(
        "user_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_type", sa.String(30), nullable=False, server_default="local"),
        sa.Column("provider_tenant_id", sa.String(100)),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("email_at_link_time", postgresql.CITEXT()),
        sa.Column("password_hash", sa.Text()),
        sa.Column("password_changed_at", sa.DateTime(timezone=True)),
        sa.Column("mfa_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_activation"),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("provider_type IN ('local', 'microsoft_entra')", name="ck_identities_provider"),
        sa.CheckConstraint("status IN ('pending_activation', 'active', 'disabled', 'locked')", name="ck_identities_status"),
        sa.UniqueConstraint("provider_type", "provider_tenant_id", "provider_subject", name="uq_identity_provider_subject"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("user_identities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("user_agent", sa.Text()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id", "expires_at"])

    op.create_table(
        "departments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("code", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Bangkok"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('active', 'suspended', 'disabled')", name="ck_departments_status"),
        sa.CheckConstraint("retention_days BETWEEN 1 AND 3650", name="ck_departments_retention"),
    )

    op.create_table(
        "department_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("department_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("departments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('owner', 'admin', 'member', 'viewer')", name="ck_memberships_role"),
        sa.CheckConstraint("status IN ('active', 'invited', 'disabled')", name="ck_memberships_status"),
        sa.UniqueConstraint("department_id", "user_id", name="uq_membership_department_user"),
    )
    op.create_index("ix_memberships_user", "department_memberships", ["user_id", "status"])

    for table in ("departments", "department_memberships"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    tenant_expression = """
      department_id = NULLIF(current_setting('app.department_id', true), '')::uuid
      OR current_setting('app.system_role', true) = 'super_admin'
    """
    op.execute(
        "CREATE POLICY departments_tenant_isolation ON departments "
        "USING (id = NULLIF(current_setting('app.department_id', true), '')::uuid "
        "OR current_setting('app.system_role', true) = 'super_admin') "
        "WITH CHECK (id = NULLIF(current_setting('app.department_id', true), '')::uuid "
        "OR current_setting('app.system_role', true) = 'super_admin')"
    )
    op.execute(
        f"CREATE POLICY memberships_tenant_isolation ON department_memberships "
        f"USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
    )

    app_role = _app_role()
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{app_role}"')
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("department_memberships")
    op.drop_table("departments")
    op.drop_table("auth_sessions")
    op.drop_table("user_identities")
    op.drop_table("users")

