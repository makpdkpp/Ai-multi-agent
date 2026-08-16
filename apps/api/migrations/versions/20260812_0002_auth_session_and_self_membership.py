"""Add CSRF token and self-service membership policies.

Revision ID: 20260812_0002
Revises: 20260812_0001
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0002"
down_revision: str | None = "20260812_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("csrf_token_hash", sa.String(64), nullable=True))
    op.execute("UPDATE auth_sessions SET csrf_token_hash = encode(gen_random_bytes(32), 'hex')")
    op.alter_column("auth_sessions", "csrf_token_hash", nullable=False)

    op.execute("DROP POLICY memberships_tenant_isolation ON department_memberships")
    op.execute("DROP POLICY departments_tenant_isolation ON departments")

    super_admin = "current_setting('app.system_role', true) = 'super_admin'"
    tenant_id = "NULLIF(current_setting('app.department_id', true), '')::uuid"
    user_id = "NULLIF(current_setting('app.user_id', true), '')::uuid"

    op.execute(
        "CREATE POLICY memberships_select ON department_memberships FOR SELECT USING ("
        f"user_id = {user_id} OR department_id = {tenant_id} OR {super_admin})"
    )
    op.execute(
        "CREATE POLICY memberships_write ON department_memberships FOR ALL USING ("
        f"department_id = {tenant_id} OR {super_admin}) WITH CHECK ("
        f"department_id = {tenant_id} OR {super_admin})"
    )
    op.execute(
        "CREATE POLICY departments_select ON departments FOR SELECT USING ("
        f"id = {tenant_id} OR {super_admin} OR EXISTS ("
        "SELECT 1 FROM department_memberships membership "
        f"WHERE membership.department_id = departments.id AND membership.user_id = {user_id}"
        "))"
    )
    op.execute(
        "CREATE POLICY departments_write ON departments FOR ALL USING ("
        f"id = {tenant_id} OR {super_admin}) WITH CHECK ("
        f"id = {tenant_id} OR {super_admin})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY departments_write ON departments")
    op.execute("DROP POLICY departments_select ON departments")
    op.execute("DROP POLICY memberships_write ON department_memberships")
    op.execute("DROP POLICY memberships_select ON department_memberships")
    op.drop_column("auth_sessions", "csrf_token_hash")

