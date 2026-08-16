from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentdesk_api.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT(), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    system_role: Mapped[str] = mapped_column(String(30), default="standard_user")
    status: Mapped[str] = mapped_column(String(20), default="invited")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    identities: Mapped[list[UserIdentity]] = relationship(back_populates="user")
    memberships: Mapped[list[DepartmentMembership]] = relationship(back_populates="user")


class UserIdentity(TimestampMixin, Base):
    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "provider_type",
            "provider_tenant_id",
            "provider_subject",
            name="uq_identity_provider_subject",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider_type: Mapped[str] = mapped_column(String(30), default="local")
    provider_tenant_id: Mapped[str | None] = mapped_column(String(100))
    provider_subject: Mapped[str] = mapped_column(String(255))
    email_at_link_time: Mapped[str | None] = mapped_column(CITEXT())
    password_hash: Mapped[str | None] = mapped_column(Text())
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mfa_required: Mapped[bool] = mapped_column(Boolean(), default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending_activation")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="identities")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    identity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_identities.id", ondelete="CASCADE")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token_hash: Mapped[str] = mapped_column(String(64))
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Bangkok")
    status: Mapped[str] = mapped_column(String(20), default="active")
    retention_days: Mapped[int] = mapped_column(Integer(), default=90)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list[DepartmentMembership]] = relationship(back_populates="department")
    agents: Mapped[list[Agent]] = relationship(back_populates="department")


class DepartmentMembership(TimestampMixin, Base):
    __tablename__ = "department_memberships"
    __table_args__ = (
        UniqueConstraint("department_id", "user_id", name="uq_membership_department_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="active")

    department: Mapped[Department] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class LlmProvider(TimestampMixin, Base):
    __tablename__ = "llm_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_type: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(100))
    base_url: Mapped[str] = mapped_column(Text())
    secret_ref: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(20), default="active")

    models: Mapped[list[LlmModel]] = relationship(back_populates="provider")


class LlmModel(Base):
    __tablename__ = "llm_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_key", name="uq_llm_models_provider_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_providers.id"))
    model_key: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    context_window: Mapped[int | None] = mapped_column(Integer())
    supports_tools: Mapped[bool] = mapped_column(Boolean(), default=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean(), default=True)
    status: Mapped[str] = mapped_column(String(20), default="active")

    provider: Mapped[LlmProvider] = relationship(back_populates="models")
    pricing_versions: Mapped[list[ModelPricingVersion]] = relationship(back_populates="model")


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("department_id", "slug", name="uq_agents_department_slug"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text())
    status: Mapped[str] = mapped_column(String(20), default="draft")
    default_language: Mapped[str] = mapped_column(String(10), default="th")
    handoff_enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    confidence_threshold: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.6000"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    department: Mapped[Department] = relationship(back_populates="agents")
    prompt_versions: Mapped[list[AgentPromptVersion]] = relationship(back_populates="agent")
    permissions: Mapped[list[AgentPermission]] = relationship(back_populates="agent")
    llm_configs: Mapped[list[AgentLlmConfig]] = relationship(back_populates="agent")
    chat_conversations: Mapped[list[ChatConversation]] = relationship(back_populates="agent")


class AgentPromptVersion(Base):
    __tablename__ = "agent_prompt_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version", name="uq_agent_prompt_versions_agent_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer(), default=1)
    system_prompt: Mapped[str] = mapped_column(Text())
    response_style: Mapped[str | None] = mapped_column(Text())
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="prompt_versions")


class AgentPermission(TimestampMixin, Base):
    __tablename__ = "agent_permissions"
    __table_args__ = (
        UniqueConstraint("agent_id", "channel", name="uq_agent_permissions_agent_channel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(30))
    enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    allow_anonymous: Mapped[bool] = mapped_column(Boolean(), default=False)

    agent: Mapped[Agent] = relationship(back_populates="permissions")


class AgentLlmConfig(TimestampMixin, Base):
    __tablename__ = "agent_llm_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    provider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_providers.id"))
    model_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_models.id"))
    model_key: Mapped[str] = mapped_column(String(200))
    temperature: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("0.20"))
    top_p: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("1.00"))
    max_output_tokens: Mapped[int] = mapped_column(Integer(), default=1024)
    input_per_million: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("0.15000000"),
    )
    output_per_million: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        default=Decimal("0.60000000"),
    )
    cached_input_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    status: Mapped[str] = mapped_column(String(20), default="active")

    agent: Mapped[Agent] = relationship(back_populates="llm_configs")


class ChatConversation(TimestampMixin, Base):
    __tablename__ = "chat_conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent] = relationship(back_populates="chat_conversations")
    messages: Mapped[list[ChatMessage]] = relationship(back_populates="conversation")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_conversations.id", ondelete="CASCADE")
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    sender_type: Mapped[str] = mapped_column(String(20))
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text())
    usage_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_usage_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[ChatConversation] = relationship(back_populates="messages")


class ModelPricingVersion(Base):
    __tablename__ = "model_pricing_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_models.id"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    input_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    output_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    cached_input_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(Text(), default="manual")

    model: Mapped[LlmModel] = relationship(back_populates="pricing_versions")


class ExchangeRate(Base):
    __tablename__ = "exchange_rates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD")
    quote_currency: Mapped[str] = mapped_column(String(3), default="THB")
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    source: Mapped[str] = mapped_column(String(100))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="live")


class DepartmentBudget(TimestampMixin, Base):
    __tablename__ = "department_budgets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    currency: Mapped[str] = mapped_column(String(3), default="THB")
    limit_amount: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    period_type: Mapped[str] = mapped_column(String(20), default="monthly")
    period_start_day: Mapped[int] = mapped_column(Integer(), default=1)
    action_on_exceed: Mapped[str] = mapped_column(String(30), default="notify_only")
    warning_thresholds: Mapped[list[int]] = mapped_column(JSONB(), default=lambda: [70, 90, 100])
    enabled: Mapped[bool] = mapped_column(Boolean(), default=True)


class LlmUsageEvent(Base):
    __tablename__ = "llm_usage_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    message_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_trace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    parent_event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("llm_usage_events.id"))
    usage_type: Mapped[str] = mapped_column(String(40))
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_providers.id"))
    model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("llm_models.id"))
    pricing_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("model_pricing_versions.id")
    )
    exchange_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exchange_rates.id"))
    input_tokens: Mapped[int] = mapped_column(BigInteger())
    output_tokens: Mapped[int] = mapped_column(BigInteger())
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger(), default=0)
    provider_cost_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    infrastructure_cost_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=0)
    display_cost_usd: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    display_cost_thb: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    exchange_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    pricing_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB())
    latency_ms: Mapped[int | None] = mapped_column(Integer())
    status: Mapped[str] = mapped_column(String(20), default="succeeded")
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LocalCostSetting(Base):
    __tablename__ = "local_cost_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mode: Mapped[str] = mapped_column(String(40), default="zero_provider_cost")
    hourly_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    allocation_method: Mapped[str] = mapped_column(String(30), default="token")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
