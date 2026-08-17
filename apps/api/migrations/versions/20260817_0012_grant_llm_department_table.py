"""Grant app role access to department LLM grants."""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

from alembic import op

revision: str = "20260817_0012"
down_revision: str | None = "20260817_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    role = _app_role()
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE department_llm_model_grants TO "{role}"'
    )


def downgrade() -> None:
    role = _app_role()
    op.execute(
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLE department_llm_model_grants FROM "{role}"'
    )
