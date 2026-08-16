"""Grant chat tables to the application role.

Revision ID: 20260816_0009
Revises: 20260816_0008
Create Date: 2026-08-16
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

from alembic import op

revision: str = "20260816_0009"
down_revision: str | None = "20260816_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    app_role = _app_role()
    for table in ("chat_conversations", "chat_messages"):
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO "{app_role}"')


def downgrade() -> None:
    app_role = _app_role()
    for table in ("chat_conversations", "chat_messages"):
        op.execute(f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE {table} FROM "{app_role}"')
