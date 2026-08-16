"""Align department membership roles with admin UI.

Revision ID: 20260816_0006
Revises: 20260816_0005
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0006"
down_revision: str | None = "20260816_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_department_memberships_ck_memberships_role"),
        "department_memberships",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_department_memberships_ck_memberships_status"),
        "department_memberships",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_department_memberships_role"),
        "department_memberships",
        "role IN ('department_admin', 'agent_manager', 'staff', 'viewer')",
    )
    op.create_check_constraint(
        op.f("ck_department_memberships_status"),
        "department_memberships",
        "status IN ('active', 'suspended')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_department_memberships_status"),
        "department_memberships",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_department_memberships_role"),
        "department_memberships",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_department_memberships_ck_memberships_status"),
        "department_memberships",
        "status IN ('active', 'invited', 'disabled')",
    )
    op.create_check_constraint(
        op.f("ck_department_memberships_ck_memberships_role"),
        "department_memberships",
        "role IN ('owner', 'admin', 'member', 'viewer')",
    )
