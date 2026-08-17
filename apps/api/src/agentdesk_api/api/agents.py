from __future__ import annotations

import asyncio
import os
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentdesk_api.api.auth import (
    AppSettings,
    AuthContext,
    AuthDependency,
    CsrfDependency,
    DbSession,
)
from agentdesk_api.api.departments import get_department_or_404
from agentdesk_api.api.usage import (
    UsageEventPayload,
    calculate_cost,
    get_or_create_model,
    get_or_create_pricing,
    get_or_create_provider,
    latest_exchange_rate,
    money,
)
from agentdesk_api.config import Settings
from agentdesk_api.db.models import (
    Agent,
    AgentLlmConfig,
    AgentPermission,
    AgentPromptVersion,
    DepartmentBudget,
    DepartmentLlmModelGrant,
    DepartmentMembership,
    LlmModel,
    LlmUsageEvent,
)
from agentdesk_api.source_context import build_agent_data_source_context, build_runtime_context

router = APIRouter(tags=["agents"])
_slug_pattern = re.compile(r"^[a-z][a-z0-9-]{1,79}$")
Channel = Literal["internal_chat", "public_widget", "email"]
AgentStatus = Literal["draft", "active", "paused", "disabled"]


class ChannelPermissionPayload(BaseModel):
    channel: Channel
    enabled: bool = True
    allow_anonymous: bool = False


class AgentLlmConfigPayload(BaseModel):
    model_id: UUID | None = None
    model_key: str = Field(default="openai/gpt-4o-mini", min_length=1, max_length=200)
    temperature: Decimal = Field(default=Decimal("0.20"), ge=Decimal("0"), le=Decimal("2"))
    top_p: Decimal = Field(default=Decimal("1.00"), gt=Decimal("0"), le=Decimal("1"))
    max_output_tokens: int = Field(default=1024, ge=1, le=200000)
    input_per_million: Decimal = Field(default=Decimal("0.15000000"), ge=Decimal("0"))
    output_per_million: Decimal = Field(default=Decimal("0.60000000"), ge=Decimal("0"))
    cached_input_per_million: Decimal | None = Field(default=None, ge=Decimal("0"))

    @field_validator("model_key")
    @classmethod
    def normalize_model_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Model key is required")
        return normalized


class AgentCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: AgentStatus = "draft"
    default_language: str = Field(default="th", min_length=2, max_length=10)
    handoff_enabled: bool = True
    confidence_threshold: Decimal = Field(
        default=Decimal("0.6000"),
        ge=Decimal("0"),
        le=Decimal("1"),
    )
    system_prompt: str = Field(min_length=1, max_length=20000)
    response_style: str | None = Field(default=None, max_length=4000)
    llm_config: AgentLlmConfigPayload = Field(default_factory=AgentLlmConfigPayload)
    permissions: list[ChannelPermissionPayload] = Field(
        default_factory=lambda: [
            ChannelPermissionPayload(channel="internal_chat", enabled=True),
            ChannelPermissionPayload(channel="public_widget", enabled=False, allow_anonymous=True),
            ChannelPermissionPayload(channel="email", enabled=False),
        ]
    )

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _slug_pattern.fullmatch(normalized):
            raise ValueError(
                "Slug must start with a letter and contain lowercase letters, numbers, or hyphens"
            )
        return normalized

    @field_validator("name", "system_prompt")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value is required")
        return normalized

    @field_validator("description", "response_style")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_unique_channels(self) -> AgentCreate:
        channels = [permission.channel for permission in self.permissions]
        if len(channels) != len(set(channels)):
            raise ValueError("Each channel can be configured only once")
        internal_chat_enabled = any(
            permission.channel == "internal_chat" and permission.enabled
            for permission in self.permissions
        )
        if not internal_chat_enabled:
            raise ValueError("Internal chat must be enabled for MVP agents")
        return self


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    status: AgentStatus | None = None
    default_language: str | None = Field(default=None, min_length=2, max_length=10)
    handoff_enabled: bool | None = None
    confidence_threshold: Decimal | None = Field(default=None, ge=Decimal("0"), le=Decimal("1"))
    system_prompt: str | None = Field(default=None, min_length=1, max_length=20000)
    response_style: str | None = Field(default=None, max_length=4000)
    llm_config: AgentLlmConfigPayload | None = None
    permissions: list[ChannelPermissionPayload] | None = None

    @field_validator("name", "system_prompt")
    @classmethod
    def normalize_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Value is required")
        return normalized

    @field_validator("description", "response_style")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_unique_channels(self) -> AgentUpdate:
        if self.permissions is None:
            return self
        channels = [permission.channel for permission in self.permissions]
        if len(channels) != len(set(channels)):
            raise ValueError("Each channel can be configured only once")
        internal_chat_enabled = any(
            permission.channel == "internal_chat" and permission.enabled
            for permission in self.permissions
        )
        if not internal_chat_enabled:
            raise ValueError("Internal chat must be enabled for MVP agents")
        return self


class AgentView(BaseModel):
    id: UUID
    department_id: UUID
    slug: str
    name: str
    description: str | None
    status: str
    default_language: str
    handoff_enabled: bool
    confidence_threshold: Decimal
    system_prompt: str
    response_style: str | None
    llm_config: dict[str, object]
    permissions: list[dict[str, object]]
    created_at: datetime
    updated_at: datetime


class AgentInvokeMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content is required")
        return normalized


class AgentInvokePayload(BaseModel):
    messages: list[AgentInvokeMessage] = Field(min_length=1, max_length=40)
    channel: Channel = "internal_chat"
    conversation_id: UUID | None = None
    message_id: UUID | None = None

    @model_validator(mode="after")
    def require_latest_user_message(self) -> AgentInvokePayload:
        if self.messages[-1].role != "user":
            raise ValueError("Last message must be from user")
        return self


async def set_auth_context(session: AsyncSession, auth: AuthContext) -> None:
    await session.execute(
        text("SELECT set_config('app.system_role', :role, true)"),
        {"role": auth.system_role},
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(auth.user_id)},
    )


def active_prompt(agent: Agent) -> AgentPromptVersion:
    prompt = next((item for item in agent.prompt_versions if item.is_active), None)
    if prompt is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent prompt missing.",
        )
    return prompt


def active_llm_config(agent: Agent) -> AgentLlmConfig:
    config = next((item for item in agent.llm_configs if item.status == "active"), None)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Agent LLM config missing.",
        )
    return config


def approx_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def estimate_input_tokens(system_prompt: str, messages: list[AgentInvokeMessage]) -> int:
    message_tokens = sum(approx_tokens(message.content) for message in messages)
    return approx_tokens(system_prompt) + message_tokens


def agent_data(agent: Agent) -> dict[str, object]:
    prompt = active_prompt(agent)
    config = active_llm_config(agent)
    return AgentView(
        id=agent.id,
        department_id=agent.department_id,
        slug=agent.slug,
        name=agent.name,
        description=agent.description,
        status=agent.status,
        default_language=agent.default_language,
        handoff_enabled=agent.handoff_enabled,
        confidence_threshold=agent.confidence_threshold,
        system_prompt=prompt.system_prompt,
        response_style=prompt.response_style,
        llm_config={
            "model_id": str(config.model_id) if config.model_id else None,
            "model_key": config.model_key,
            "temperature": str(config.temperature),
            "top_p": str(config.top_p),
            "max_output_tokens": config.max_output_tokens,
            "input_per_million": str(config.input_per_million),
            "output_per_million": str(config.output_per_million),
            "cached_input_per_million": str(config.cached_input_per_million)
            if config.cached_input_per_million is not None
            else None,
        },
        permissions=[
            {
                "channel": permission.channel,
                "enabled": permission.enabled,
                "allow_anonymous": permission.allow_anonymous,
            }
            for permission in sorted(agent.permissions, key=lambda item: item.channel)
        ],
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    ).model_dump(mode="json")


def agent_load_options():
    return (
        selectinload(Agent.prompt_versions),
        selectinload(Agent.permissions),
        selectinload(Agent.llm_configs).selectinload(AgentLlmConfig.provider),
        selectinload(Agent.llm_configs).selectinload(AgentLlmConfig.model),
    )


def llm_connection(config: AgentLlmConfig, settings: Settings) -> tuple[str, str | None]:
    provider = config.provider
    base_url = provider.base_url if provider and provider.base_url else settings.openrouter_base_url
    api_key = os.getenv(provider.secret_ref) if provider and provider.secret_ref else None
    # Keep legacy profiles usable when the UI was configured with a missing or
    # literal secret reference. New profiles should use an env var name.
    if not api_key:
        api_key = settings.openrouter_api_key
    # OpenAI-compatible local servers (LM Studio/Ollama/vLLM) commonly do not
    # require authentication. httpx still receives a harmless bearer value so
    # the request shape remains compatible with OpenAI-compatible gateways.
    if not api_key and provider and provider.provider_type in {"ollama", "vllm", "manual"}:
        api_key = "local"
    return base_url, api_key


async def get_agent_or_404(agent_id: UUID, session: DbSession) -> Agent:
    agent = await session.scalar(
        select(Agent)
        .options(*agent_load_options())
        .where(Agent.id == agent_id, Agent.deleted_at.is_(None))
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


async def set_agent_department_context(
    session: AsyncSession,
    auth: AuthContext,
    agent: Agent,
) -> None:
    await set_auth_context(session, auth)
    await session.execute(
        text("SELECT set_config('app.department_id', :department_id, true)"),
        {"department_id": str(agent.department_id)},
    )


async def require_agent_member_access(
    agent: Agent,
    auth: AuthContext,
    session: AsyncSession,
) -> None:
    await set_agent_department_context(session, auth, agent)
    if auth.system_role == "super_admin":
        return
    membership = await session.scalar(
        select(DepartmentMembership).where(
            DepartmentMembership.department_id == agent.department_id,
            DepartmentMembership.user_id == auth.user_id,
            DepartmentMembership.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")


async def require_department_member_access(
    department_id: UUID,
    auth: AuthContext,
    session: AsyncSession,
) -> None:
    await set_auth_context(session, auth)
    await session.execute(
        text("SELECT set_config('app.department_id', :department_id, true)"),
        {"department_id": str(department_id)},
    )
    if auth.system_role == "super_admin":
        return
    membership = await session.scalar(
        select(DepartmentMembership).where(
            DepartmentMembership.department_id == department_id,
            DepartmentMembership.user_id == auth.user_id,
            DepartmentMembership.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")


async def require_department_agent_manager_access(
    department_id: UUID,
    auth: AuthContext,
    session: AsyncSession,
) -> None:
    await require_department_member_access(department_id, auth, session)
    if auth.system_role == "super_admin":
        return
    membership = await session.scalar(
        select(DepartmentMembership).where(
            DepartmentMembership.department_id == department_id,
            DepartmentMembership.user_id == auth.user_id,
            DepartmentMembership.status == "active",
            DepartmentMembership.role.in_(("department_admin", "agent_manager")),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Department Admin or Agent Manager required.",
        )


async def validate_model_access(
    model_id: UUID | None,
    department_id: UUID,
    auth: AuthContext,
    session: AsyncSession,
) -> LlmModel | None:
    if model_id is None:
        return None
    model = await session.get(LlmModel, model_id)
    if model is None or model.status != "active":
        raise HTTPException(status_code=400, detail="Selected LLM model is not active.")
    if auth.system_role != "super_admin":
        granted = await session.scalar(
            select(DepartmentLlmModelGrant.id).where(
                DepartmentLlmModelGrant.department_id == department_id,
                DepartmentLlmModelGrant.model_id == model_id,
                DepartmentLlmModelGrant.status == "active",
            )
        )
        if granted is None:
            raise HTTPException(status_code=403, detail="แผนกนี้ไม่มีสิทธิ์ใช้ LLM รุ่นที่เลือก")
    return model


def channel_permission(agent: Agent, channel: Channel) -> AgentPermission:
    permission = next((item for item in agent.permissions if item.channel == channel), None)
    if permission is None or not permission.enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Agent channel is not enabled.",
        )
    return permission


async def budget_guard(
    session: AsyncSession,
    agent: Agent,
    channel: Channel,
    estimated_cost_usd: Decimal,
    estimated_cost_thb: Decimal,
) -> dict[str, object]:
    budget = await session.scalar(
        select(DepartmentBudget).where(
            DepartmentBudget.department_id == agent.department_id,
            DepartmentBudget.period_type == "monthly",
            DepartmentBudget.enabled.is_(True),
        )
    )
    if budget is None or budget.limit_amount == 0:
        return {"allowed": True, "budget": None}
    spent_row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LlmUsageEvent.display_cost_usd), 0),
                func.coalesce(func.sum(LlmUsageEvent.display_cost_thb), 0),
            ).where(LlmUsageEvent.department_id == agent.department_id)
        )
    ).one()
    spent = Decimal(spent_row[1]) if budget.currency == "THB" else Decimal(spent_row[0])
    projected = spent + (estimated_cost_thb if budget.currency == "THB" else estimated_cost_usd)
    percent = (
        Decimal("0")
        if budget.limit_amount == 0
        else projected * Decimal("100") / budget.limit_amount
    )
    should_pause = budget.action_on_exceed == "pause_all_llm" or (
        budget.action_on_exceed == "pause_public_widget" and channel == "public_widget"
    )
    data = {
        "currency": budget.currency,
        "limit_amount": str(money(budget.limit_amount)),
        "spent_amount": str(money(spent)),
        "projected_amount": str(money(projected)),
        "projected_percent": str(money(percent)),
        "action_on_exceed": budget.action_on_exceed,
    }
    if projected > budget.limit_amount and should_pause:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"message": "Department budget would be exceeded.", "budget": data},
        )
    return {"allowed": True, "budget": data}


def usage_payload_from_invoke(
    agent: Agent,
    config: AgentLlmConfig,
    request_trace_id: UUID,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int | None,
    provider_request_id: str | None,
    conversation_id: UUID | None,
    message_id: UUID | None,
) -> UsageEventPayload:
    return UsageEventPayload(
        department_id=agent.department_id,
        usage_type="answer_synthesis",
        model_key=config.model_key,
        display_name=config.model_key,
        request_trace_id=request_trace_id,
        agent_id=agent.id,
        conversation_id=conversation_id,
        message_id=message_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_per_million=config.input_per_million,
        output_per_million=config.output_per_million,
        cached_input_per_million=config.cached_input_per_million,
        latency_ms=latency_ms,
        provider_request_id=provider_request_id,
    )


async def record_agent_usage(
    session: AsyncSession,
    payload: UsageEventPayload,
) -> dict[str, object]:
    rate = await latest_exchange_rate(session)
    provider = await get_or_create_provider(session, payload)
    model = await get_or_create_model(session, provider, payload)
    pricing = await get_or_create_pricing(session, model, payload)
    cost = calculate_cost(payload, rate.rate)
    event = LlmUsageEvent(
        department_id=payload.department_id,
        agent_id=payload.agent_id,
        conversation_id=payload.conversation_id,
        message_id=payload.message_id,
        request_trace_id=payload.request_trace_id,
        parent_event_id=payload.parent_event_id,
        usage_type=payload.usage_type,
        provider_id=provider.id,
        model_id=model.id,
        pricing_version_id=pricing.id,
        exchange_rate_id=rate.id,
        input_tokens=payload.input_tokens,
        output_tokens=payload.output_tokens,
        cached_input_tokens=payload.cached_input_tokens,
        provider_cost_usd=cost.provider_cost_usd,
        infrastructure_cost_usd=money(payload.infrastructure_cost_usd),
        display_cost_usd=cost.display_cost_usd,
        display_cost_thb=cost.display_cost_thb,
        exchange_rate_snapshot=money(rate.rate),
        pricing_snapshot=cost.pricing_snapshot,
        latency_ms=payload.latency_ms,
        status=payload.status,
        provider_request_id=payload.provider_request_id,
    )
    session.add(event)
    await session.flush()
    return {
        "id": str(event.id),
        "input_tokens": payload.input_tokens,
        "output_tokens": payload.output_tokens,
        "display_cost_usd": str(cost.display_cost_usd),
        "display_cost_thb": str(cost.display_cost_thb),
    }


@router.get("/departments/{department_id}/agents")
async def list_department_agents(
    department_id: UUID,
    auth: AuthDependency,
    session: DbSession,
) -> dict[str, object]:
    await require_department_member_access(department_id, auth, session)
    await get_department_or_404(department_id, session)
    result = await session.execute(
        select(Agent)
        .options(*agent_load_options())
        .where(Agent.department_id == department_id, Agent.deleted_at.is_(None))
        .order_by(Agent.name)
    )
    agents = list(result.scalars().all())
    return {"data": [agent_data(agent) for agent in agents], "meta": {"total": len(agents)}}


@router.post("/departments/{department_id}/agents", status_code=status.HTTP_201_CREATED)
async def create_department_agent(
    department_id: UUID,
    payload: AgentCreate,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await require_department_agent_manager_access(department_id, auth, session)
    await get_department_or_404(department_id, session)
    selected_model = await validate_model_access(
        payload.llm_config.model_id, department_id, auth, session
    )
    agent = Agent(
        department_id=department_id,
        slug=payload.slug,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        default_language=payload.default_language,
        handoff_enabled=payload.handoff_enabled,
        confidence_threshold=payload.confidence_threshold,
        created_by=auth.user_id,
    )
    agent.prompt_versions.append(
        AgentPromptVersion(
            version=1,
            system_prompt=payload.system_prompt,
            response_style=payload.response_style,
            is_active=True,
            created_by=auth.user_id,
        )
    )
    agent.llm_configs.append(
        AgentLlmConfig(
            model_id=selected_model.id if selected_model else None,
            provider_id=selected_model.provider_id if selected_model else None,
            model_key=selected_model.model_key if selected_model else payload.llm_config.model_key,
            temperature=payload.llm_config.temperature,
            top_p=payload.llm_config.top_p,
            max_output_tokens=payload.llm_config.max_output_tokens,
            input_per_million=payload.llm_config.input_per_million,
            output_per_million=payload.llm_config.output_per_million,
            cached_input_per_million=payload.llm_config.cached_input_per_million,
            status="active",
        )
    )
    for permission in payload.permissions:
        agent.permissions.append(AgentPermission(**permission.model_dump()))
    session.add(agent)
    try:
        await session.flush()
        await session.refresh(
            agent,
            attribute_names=["prompt_versions", "permissions", "llm_configs"],
        )
        response_data = agent_data(agent)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent slug already exists in this department.",
        ) from exc
    return {"data": response_data}


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: UUID,
    auth: AuthDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    agent = await get_agent_or_404(agent_id, session)
    await require_agent_member_access(agent, auth, session)
    return {"data": agent_data(agent)}


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    agent = await get_agent_or_404(agent_id, session)
    await require_department_agent_manager_access(agent.department_id, auth, session)
    for field in (
        "name",
        "description",
        "status",
        "default_language",
        "handoff_enabled",
        "confidence_threshold",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(agent, field, value)

    if payload.system_prompt is not None or payload.response_style is not None:
        current_prompt = active_prompt(agent)
        current_prompt.is_active = False
        next_version = max(item.version for item in agent.prompt_versions) + 1
        agent.prompt_versions.append(
            AgentPromptVersion(
                version=next_version,
                system_prompt=payload.system_prompt or current_prompt.system_prompt,
                response_style=payload.response_style,
                is_active=True,
                created_by=auth.user_id,
            )
        )

    if payload.llm_config is not None:
        config = active_llm_config(agent)
        selected_model = await validate_model_access(
            payload.llm_config.model_id, agent.department_id, auth, session
        )
        config.model_id = selected_model.id if selected_model else None
        config.provider_id = selected_model.provider_id if selected_model else None
        config.model_key = (
            selected_model.model_key if selected_model else payload.llm_config.model_key
        )
        config.temperature = payload.llm_config.temperature
        config.top_p = payload.llm_config.top_p
        config.max_output_tokens = payload.llm_config.max_output_tokens
        config.input_per_million = payload.llm_config.input_per_million
        config.output_per_million = payload.llm_config.output_per_million
        config.cached_input_per_million = payload.llm_config.cached_input_per_million
        config.updated_at = datetime.now(UTC)

    if payload.permissions is not None:
        existing = {permission.channel: permission for permission in agent.permissions}
        for permission_payload in payload.permissions:
            permission = existing.get(permission_payload.channel)
            if permission is None:
                agent.permissions.append(AgentPermission(**permission_payload.model_dump()))
            else:
                permission.enabled = permission_payload.enabled
                permission.allow_anonymous = permission_payload.allow_anonymous
                permission.updated_at = datetime.now(UTC)

    agent.updated_at = datetime.now(UTC)
    await session.flush()
    await session.refresh(agent, attribute_names=["prompt_versions", "permissions", "llm_configs"])
    response_data = agent_data(agent)
    await session.commit()
    return {"data": response_data}


@router.post("/agents/{agent_id}/invoke")
async def invoke_agent(
    agent_id: UUID,
    payload: AgentInvokePayload,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
    settings: AppSettings,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    agent = await get_agent_or_404(agent_id, session)
    await require_agent_member_access(agent, auth, session)
    if agent.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent must be active before it can be invoked.",
        )
    channel_permission(agent, payload.channel)
    prompt = active_prompt(agent)
    system_prompt = f"{prompt.system_prompt}\n\n{build_runtime_context(settings)}"
    latest_query = payload.messages[-1].content if payload.messages else None
    data_source_context = await build_agent_data_source_context(
        session, settings, agent, latest_query
    )
    if data_source_context:
        system_prompt = f"{system_prompt}\n\n{data_source_context}"
    config = active_llm_config(agent)
    provider_base_url, provider_api_key = llm_connection(config, settings)
    if not provider_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM provider API key is not configured.",
        )
    estimated_input = estimate_input_tokens(system_prompt, payload.messages)
    estimate_payload = UsageEventPayload(
        department_id=agent.department_id,
        usage_type="answer_synthesis",
        model_key=config.model_key,
        input_tokens=estimated_input,
        output_tokens=config.max_output_tokens,
        input_per_million=config.input_per_million,
        output_per_million=config.output_per_million,
        cached_input_per_million=config.cached_input_per_million,
    )
    rate = await latest_exchange_rate(session)
    estimated_cost = calculate_cost(estimate_payload, rate.rate)
    budget = await budget_guard(
        session,
        agent,
        payload.channel,
        estimated_cost.display_cost_usd,
        estimated_cost.display_cost_thb,
    )

    request_trace_id = uuid4()
    started_at = datetime.now(UTC)
    openrouter_messages = [
        {"role": "system", "content": system_prompt},
        *[message.model_dump() for message in payload.messages],
    ]
    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_timeout_seconds) as client:
            response = None
            for attempt in range(2):
                response = await client.post(
                    f"{provider_base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {provider_api_key}",
                        "HTTP-Referer": settings.web_origin,
                        "X-Title": settings.openrouter_app_title,
                    },
                    json={
                        "model": config.model_key,
                        "messages": openrouter_messages,
                        "temperature": float(config.temperature),
                        "top_p": float(config.top_p),
                        "max_tokens": config.max_output_tokens,
                    },
                )
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == 1:
                    break
                retry_after = min(float(response.headers.get("Retry-After", "1")), 3.0)
                await asyncio.sleep(max(retry_after, 0.2))
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OpenRouter request timed out.",
        ) from exc
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"ไม่สามารถเชื่อมต่อ LLM provider ที่ {provider_base_url} ได้ "
                "ตรวจสอบว่า Local LM เปิด API server และตั้งค่า Base URL ให้ถูกต้อง "
                f"({exc})"
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider request failed at {provider_base_url}: {exc}",
        ) from exc

    if response.status_code == 429:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="โมเดลกำลังถูกใช้งานหนาแน่น กรุณาลองใหม่อีกครั้งในอีกสักครู่",
            headers={"Retry-After": response.headers.get("Retry-After", "2")},
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"AI provider returned {response.status_code} for model "
                f"{config.model_key}: {response.text[:300]}"
            ),
        )

    body = response.json()
    choices = body.get("choices") or []
    if not choices:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenRouter response did not include choices.",
        )
    choice = choices[0]
    answer = (choice.get("message", {}).get("content") or "").strip()
    if not answer:
        finish_reason = choice.get("finish_reason")
        if finish_reason == "length" and choice.get("message", {}).get("reasoning_content"):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "โมเดลใช้ context จนเต็มก่อนสร้างคำตอบ (reasoning ถูกตัดจบ) "
                    "กรุณาเพิ่ม Context Length ของโมเดลใน LM Studio หรือ ลดข้อมูลที่แนบกับ Agent แล้วลองใหม่"
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an empty assistant message.",
        )
    usage = body.get("usage") or {}
    input_tokens = int(usage.get("prompt_tokens") or estimated_input)
    output_tokens = int(usage.get("completion_tokens") or approx_tokens(answer))
    latency_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
    usage_data = await record_agent_usage(
        session,
        usage_payload_from_invoke(
            agent=agent,
            config=config,
            request_trace_id=request_trace_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            provider_request_id=body.get("id"),
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
        ),
    )
    await session.commit()
    return {
        "data": {
            "request_trace_id": str(request_trace_id),
            "agent_id": str(agent.id),
            "message": {"role": "assistant", "content": answer},
            "usage": usage_data,
            "budget": budget.get("budget"),
        }
    }
