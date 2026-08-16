"""Allow active department members to read department agents.

Revision ID: 20260816_0007
Revises: 20260816_0006
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0007"
down_revision: str | None = "20260816_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_expression(table_name: str = "agents") -> str:
    tenant_id = "NULLIF(current_setting('app.department_id', true), '')::uuid"
    user_id = "NULLIF(current_setting('app.user_id', true), '')::uuid"
    super_admin = "current_setting('app.system_role', true) = 'super_admin'"
    return (
        f"{table_name}.department_id = {tenant_id} "
        f"OR {super_admin} "
        "OR EXISTS ("
        "SELECT 1 FROM department_memberships membership "
        f"WHERE membership.department_id = {table_name}.department_id "
        f"AND membership.user_id = {user_id} "
        "AND membership.status = 'active'"
        ")"
    )


def _child_expression(table_name: str) -> str:
    return (
        "EXISTS (SELECT 1 FROM agents "
        f"WHERE agents.id = {table_name}.agent_id "
        f"AND ({_tenant_expression('agents')}))"
    )


def upgrade() -> None:
    op.execute("DROP POLICY agents_tenant_isolation ON agents")
    op.execute(
        "CREATE POLICY agents_tenant_isolation ON agents "
        f"USING ({_tenant_expression()}) WITH CHECK ({_tenant_expression()})"
    )

    for table in ("agent_prompt_versions", "agent_permissions", "agent_llm_configs"):
        op.execute(f"DROP POLICY {table}_tenant_isolation ON {table}")
        expression = _child_expression(table)
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )


def downgrade() -> None:
    tenant_expression = (
        "department_id = NULLIF(current_setting('app.department_id', true), '')::uuid "
        "OR current_setting('app.system_role', true) = 'super_admin'"
    )
    op.execute("DROP POLICY agents_tenant_isolation ON agents")
    op.execute(
        "CREATE POLICY agents_tenant_isolation ON agents "
        f"USING ({tenant_expression}) WITH CHECK ({tenant_expression})"
    )

    for table in ("agent_prompt_versions", "agent_permissions", "agent_llm_configs"):
        expression = (
            "EXISTS (SELECT 1 FROM agents "
            f"WHERE agents.id = {table}.agent_id "
            "AND (agents.department_id = NULLIF(current_setting('app.department_id', true), '')::uuid "
            "OR current_setting('app.system_role', true) = 'super_admin'))"
        )
        op.execute(f"DROP POLICY {table}_tenant_isolation ON {table}")
        op.execute(
            f"CREATE POLICY {table}_tenant_isolation ON {table} "
            f"USING ({expression}) WITH CHECK ({expression})"
        )
