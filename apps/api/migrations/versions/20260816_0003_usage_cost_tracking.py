"""Add usage, cost, exchange rate, and budget tables.

Revision ID: 20260816_0003
Revises: 20260812_0002
Create Date: 2026-08-16
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0003"
down_revision: str | None = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _app_role() -> str:
    role = os.getenv("POSTGRES_APP_USER", "agentdesk_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", role):
        raise RuntimeError("POSTGRES_APP_USER must be a safe PostgreSQL identifier")
    return role


def upgrade() -> None:
    op.create_table(
        "llm_providers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("secret_ref", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "provider_type IN ('openrouter', 'ollama', 'vllm', 'manual')",
            name="ck_llm_providers_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled', 'unhealthy')",
            name="ck_llm_providers_status",
        ),
    )
    op.create_index("ix_llm_providers_type_status", "llm_providers", ["provider_type", "status"])

    op.create_table(
        "llm_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_providers.id"), nullable=False),
        sa.Column("model_key", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("context_window", sa.Integer()),
        sa.Column("supports_tools", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("supports_streaming", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_llm_models_status"),
        sa.UniqueConstraint("provider_id", "model_key", name="uq_llm_models_provider_key"),
    )

    op.create_table(
        "model_pricing_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_models.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("input_per_million", sa.Numeric(20, 8), nullable=False),
        sa.Column("output_per_million", sa.Numeric(20, 8), nullable=False),
        sa.Column("cached_input_per_million", sa.Numeric(20, 8)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.CheckConstraint("currency = 'USD'", name="ck_model_pricing_currency"),
        sa.CheckConstraint("input_per_million >= 0", name="ck_model_pricing_input"),
        sa.CheckConstraint("output_per_million >= 0", name="ck_model_pricing_output"),
        sa.CheckConstraint(
            "cached_input_per_million IS NULL OR cached_input_per_million >= 0",
            name="ck_model_pricing_cached",
        ),
    )
    op.execute(
        "CREATE INDEX ix_model_pricing_model_effective "
        "ON model_pricing_versions (model_id, effective_from DESC)"
    )

    op.create_table(
        "exchange_rates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("quote_currency", sa.String(3), nullable=False, server_default="THB"),
        sa.Column("rate", sa.Numeric(20, 8), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("status", sa.String(20), nullable=False, server_default="live"),
        sa.CheckConstraint("base_currency = 'USD'", name="ck_exchange_base_usd"),
        sa.CheckConstraint("quote_currency = 'THB'", name="ck_exchange_quote_thb"),
        sa.CheckConstraint("rate > 0", name="ck_exchange_rate_positive"),
        sa.CheckConstraint(
            "status IN ('live', 'stale', 'manual_fallback')",
            name="ck_exchange_status",
        ),
    )
    op.execute(
        "CREATE INDEX ix_exchange_rates_pair_effective "
        "ON exchange_rates (base_currency, quote_currency, effective_at DESC)"
    )

    op.create_table(
        "department_budgets",
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
        sa.Column("currency", sa.String(3), nullable=False, server_default="THB"),
        sa.Column("limit_amount", sa.Numeric(20, 8), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("period_start_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("action_on_exceed", sa.String(30), nullable=False, server_default="notify_only"),
        sa.Column(
            "warning_thresholds",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[70, 90, 100]'::jsonb"),
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("currency IN ('USD', 'THB')", name="ck_department_budgets_currency"),
        sa.CheckConstraint("limit_amount >= 0", name="ck_department_budgets_limit"),
        sa.CheckConstraint("period_type = 'monthly'", name="ck_department_budgets_period"),
        sa.CheckConstraint("period_start_day BETWEEN 1 AND 28", name="ck_department_budgets_start_day"),
        sa.CheckConstraint(
            "action_on_exceed IN ('notify_only', 'pause_public_widget', 'pause_all_llm')",
            name="ck_department_budgets_action",
        ),
        sa.UniqueConstraint("department_id", "period_type", name="uq_department_budgets_period"),
    )

    op.create_table(
        "llm_usage_events",
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
        sa.Column("agent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True)),
        sa.Column("message_id", postgresql.UUID(as_uuid=True)),
        sa.Column("request_trace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_event_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_usage_events.id")),
        sa.Column("usage_type", sa.String(40), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_providers.id"), nullable=False),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("llm_models.id"), nullable=False),
        sa.Column(
            "pricing_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_pricing_versions.id"),
        ),
        sa.Column("exchange_rate_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("exchange_rates.id")),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("provider_cost_usd", sa.Numeric(20, 8), nullable=False),
        sa.Column("infrastructure_cost_usd", sa.Numeric(20, 8), nullable=False, server_default="0"),
        sa.Column("display_cost_usd", sa.Numeric(20, 8), nullable=False),
        sa.Column("display_cost_thb", sa.Numeric(20, 8), nullable=False),
        sa.Column("exchange_rate_snapshot", sa.Numeric(20, 8), nullable=False),
        sa.Column("pricing_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False, server_default="succeeded"),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("input_tokens >= 0", name="ck_usage_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="ck_usage_output_tokens"),
        sa.CheckConstraint("cached_input_tokens >= 0", name="ck_usage_cached_tokens"),
        sa.CheckConstraint("provider_cost_usd >= 0", name="ck_usage_provider_cost"),
        sa.CheckConstraint("infrastructure_cost_usd >= 0", name="ck_usage_infra_cost"),
        sa.CheckConstraint("display_cost_usd >= 0", name="ck_usage_display_usd"),
        sa.CheckConstraint("display_cost_thb >= 0", name="ck_usage_display_thb"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed', 'cancelled')",
            name="ck_usage_status",
        ),
    )
    op.execute(
        "CREATE INDEX ix_usage_department_created "
        "ON llm_usage_events (department_id, created_at DESC)"
    )
    op.create_index("ix_usage_trace", "llm_usage_events", ["request_trace_id"])

    op.create_table(
        "local_cost_settings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("mode", sa.String(40), nullable=False, server_default="zero_provider_cost"),
        sa.Column("hourly_cost_usd", sa.Numeric(20, 8)),
        sa.Column("allocation_method", sa.String(30), nullable=False, server_default="token"),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.CheckConstraint(
            "mode IN ('zero_provider_cost', 'estimated_infrastructure_cost')",
            name="ck_local_cost_mode",
        ),
        sa.CheckConstraint(
            "allocation_method IN ('gpu_seconds', 'request', 'token')",
            name="ck_local_cost_allocation",
        ),
        sa.CheckConstraint(
            "hourly_cost_usd IS NULL OR hourly_cost_usd >= 0",
            name="ck_local_cost_hourly",
        ),
    )

    op.execute(
        "INSERT INTO exchange_rates "
        "(base_currency, quote_currency, rate, source, effective_at, status) "
        "VALUES ('USD', 'THB', 35.00000000, 'manual_seed', now(), 'manual_fallback')"
    )

    for table in ("department_budgets", "llm_usage_events"):
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

    app_role = _app_role()
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_role}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_role}"')


def downgrade() -> None:
    op.drop_table("local_cost_settings")
    op.drop_table("llm_usage_events")
    op.drop_table("department_budgets")
    op.drop_table("exchange_rates")
    op.drop_table("model_pricing_versions")
    op.drop_table("llm_models")
    op.drop_table("llm_providers")
