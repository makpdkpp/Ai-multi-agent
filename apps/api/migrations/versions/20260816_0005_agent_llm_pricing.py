"""Add pricing fields to agent LLM configs.

Revision ID: 20260816_0005
Revises: 20260816_0004
Create Date: 2026-08-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260816_0005"
down_revision: str | None = "20260816_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_llm_configs",
        sa.Column(
            "input_per_million",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0.15000000",
        ),
    )
    op.add_column(
        "agent_llm_configs",
        sa.Column(
            "output_per_million",
            sa.Numeric(20, 8),
            nullable=False,
            server_default="0.60000000",
        ),
    )
    op.add_column(
        "agent_llm_configs",
        sa.Column("cached_input_per_million", sa.Numeric(20, 8)),
    )
    op.create_check_constraint(
        "ck_agent_llm_input_price",
        "agent_llm_configs",
        "input_per_million >= 0",
    )
    op.create_check_constraint(
        "ck_agent_llm_output_price",
        "agent_llm_configs",
        "output_per_million >= 0",
    )
    op.create_check_constraint(
        "ck_agent_llm_cached_price",
        "agent_llm_configs",
        "cached_input_per_million IS NULL OR cached_input_per_million >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_llm_cached_price", "agent_llm_configs", type_="check")
    op.drop_constraint("ck_agent_llm_output_price", "agent_llm_configs", type_="check")
    op.drop_constraint("ck_agent_llm_input_price", "agent_llm_configs", type_="check")
    op.drop_column("agent_llm_configs", "cached_input_per_million")
    op.drop_column("agent_llm_configs", "output_per_million")
    op.drop_column("agent_llm_configs", "input_per_million")
