from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from agentdesk_api.api.auth import CsrfDependency, DbSession, SuperAdminDependency
from agentdesk_api.api.departments import get_department_or_404
from agentdesk_api.db.models import Agent, AgentLlmConfig, AgentPermission, AgentPromptVersion

router = APIRouter(tags=["agents"])
_slug_pattern = re.compile(r"^[a-z][a-z0-9-]{1,79}$")
Channel = Literal["internal_chat", "public_widget", "email"]
AgentStatus = Literal["draft", "active", "paused", "disabled"]


class ChannelPermissionPayload(BaseModel):
    channel: Channel
    enabled: bool = True
    allow_anonymous: bool = False


class AgentLlmConfigPayload(BaseModel):
    model_key: str = Field(default="openai/gpt-4o-mini", min_length=1, max_length=200)
    temperature: Decimal = Field(default=Decimal("0.20"), ge=Decimal("0"), le=Decimal("2"))
    top_p: Decimal = Field(default=Decimal("1.00"), gt=Decimal("0"), le=Decimal("1"))
    max_output_tokens: int = Field(default=1024, ge=1, le=200000)

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


async def set_super_admin_context(session: DbSession, role: str) -> None:
    await session.execute(text("SELECT set_config('app.system_role', :role, true)"), {"role": role})


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
            "model_key": config.model_key,
            "temperature": str(config.temperature),
            "top_p": str(config.top_p),
            "max_output_tokens": config.max_output_tokens,
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
        selectinload(Agent.llm_configs),
    )


async def get_agent_or_404(agent_id: UUID, session: DbSession) -> Agent:
    agent = await session.scalar(
        select(Agent)
        .options(*agent_load_options())
        .where(Agent.id == agent_id, Agent.deleted_at.is_(None))
    )
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found.")
    return agent


@router.get("/departments/{department_id}/agents")
async def list_department_agents(
    department_id: UUID,
    auth: SuperAdminDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
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
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    await get_department_or_404(department_id, session)
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
            model_key=payload.llm_config.model_key,
            temperature=payload.llm_config.temperature,
            top_p=payload.llm_config.top_p,
            max_output_tokens=payload.llm_config.max_output_tokens,
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
    auth: SuperAdminDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    return {"data": agent_data(await get_agent_or_404(agent_id, session))}


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    agent = await get_agent_or_404(agent_id, session)
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
        config.model_key = payload.llm_config.model_key
        config.temperature = payload.llm_config.temperature
        config.top_p = payload.llm_config.top_p
        config.max_output_tokens = payload.llm_config.max_output_tokens
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
