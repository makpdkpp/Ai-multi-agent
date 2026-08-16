from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.orm import selectinload

from agentdesk_api.api.agents import (
    AgentInvokeMessage,
    UsageEventPayload,
    active_llm_config,
    active_prompt,
    approx_tokens,
    budget_guard,
    calculate_cost,
    channel_permission,
    estimate_input_tokens,
    get_agent_or_404,
    latest_exchange_rate,
    record_agent_usage,
    require_agent_member_access,
    set_agent_department_context,
    set_auth_context,
    usage_payload_from_invoke,
)
from agentdesk_api.api.auth import AppSettings, AuthDependency, CsrfDependency, DbSession
from agentdesk_api.db.models import ChatConversation, ChatMessage, LlmUsageEvent
from agentdesk_api.source_context import build_agent_data_source_context

router = APIRouter(prefix="/chat", tags=["chat"])


class ConversationCreate(BaseModel):
    agent_id: UUID
    title: str | None = Field(default=None, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ChatSendPayload(BaseModel):
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Message content is required")
        return normalized


def usage_event_data(event: LlmUsageEvent | None) -> dict[str, object] | None:
    if event is None:
        return None
    return {
        "id": str(event.id),
        "input_tokens": event.input_tokens,
        "output_tokens": event.output_tokens,
        "display_cost_usd": str(event.display_cost_usd),
        "display_cost_thb": str(event.display_cost_thb),
    }


def message_data(
    message: ChatMessage,
    usage_by_message_id: dict[UUID, LlmUsageEvent] | None = None,
) -> dict[str, object]:
    usage_event = (
        usage_by_message_id.get(message.id)
        if usage_by_message_id is not None and message.usage_event_id
        else None
    )
    data = {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "sender_type": message.sender_type,
        "content": message.content,
        "usage_event_id": str(message.usage_event_id) if message.usage_event_id else None,
        "created_at": message.created_at.isoformat(),
    }
    if usage_event is not None:
        data["usage"] = usage_event_data(usage_event)
    return data


async def message_usage_events(
    session: DbSession,
    messages: list[ChatMessage],
) -> dict[UUID, LlmUsageEvent]:
    message_ids = [message.id for message in messages if message.usage_event_id is not None]
    if not message_ids:
        return {}
    result = await session.execute(
        select(LlmUsageEvent).where(LlmUsageEvent.message_id.in_(message_ids))
    )
    return {
        event.message_id: event
        for event in result.scalars().all()
        if event.message_id is not None
    }


async def conversation_usage(session: DbSession, conversation_id: UUID) -> dict[str, object]:
    row = (
        await session.execute(
            select(
                func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
                func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
                func.count(LlmUsageEvent.id),
                func.coalesce(func.sum(LlmUsageEvent.display_cost_usd), 0),
                func.coalesce(func.sum(LlmUsageEvent.display_cost_thb), 0),
            ).where(LlmUsageEvent.conversation_id == conversation_id)
        )
    ).one()
    return {
        "input_tokens": int(row[0]),
        "output_tokens": int(row[1]),
        "requests": int(row[2]),
        "display_cost_usd": str(Decimal(row[3])),
        "display_cost_thb": str(Decimal(row[4])),
    }


async def conversation_data(
    conversation: ChatConversation,
    session: DbSession,
    include_messages: bool = False,
) -> dict[str, object]:
    data = {
        "id": str(conversation.id),
        "department_id": str(conversation.department_id),
        "agent_id": str(conversation.agent_id),
        "agent_name": conversation.agent.name if conversation.agent else None,
        "title": conversation.title,
        "status": conversation.status,
        "last_message_at": conversation.last_message_at.isoformat()
        if conversation.last_message_at
        else None,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "usage": await conversation_usage(session, conversation.id),
    }
    if include_messages:
        usage_by_message_id = await message_usage_events(session, conversation.messages)
        data["messages"] = [
            message_data(message, usage_by_message_id) for message in conversation.messages
        ]
    return data


async def set_conversation_department_context(
    session: DbSession,
    conversation: ChatConversation,
) -> None:
    await session.execute(
        text("SELECT set_config('app.department_id', :department_id, true)"),
        {"department_id": str(conversation.department_id)},
    )


async def get_conversation_or_404(
    conversation_id: UUID,
    session: DbSession,
) -> ChatConversation:
    conversation = await session.scalar(
        select(ChatConversation)
        .options(
            selectinload(ChatConversation.agent),
            selectinload(ChatConversation.messages),
        )
        .where(ChatConversation.id == conversation_id)
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conversation


@router.get("/conversations")
async def list_conversations(
    auth: AuthDependency,
    session: DbSession,
    department_id: UUID | None = None,
    agent_id: UUID | None = None,
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, object]:
    await set_auth_context(session, auth)
    statement = (
        select(ChatConversation)
        .options(selectinload(ChatConversation.agent))
        .order_by(ChatConversation.updated_at.desc(), ChatConversation.created_at.desc())
        .limit(limit)
    )
    if department_id is not None:
        statement = statement.where(ChatConversation.department_id == department_id)
    if agent_id is not None:
        statement = statement.where(ChatConversation.agent_id == agent_id)
    result = await session.execute(statement)
    conversations = list(result.scalars().all())
    data = []
    for conversation in conversations:
        await set_conversation_department_context(session, conversation)
        data.append(await conversation_data(conversation, session))
    return {
        "data": data,
        "meta": {"total": len(conversations)},
    }


@router.post("/conversations", status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    agent = await get_agent_or_404(payload.agent_id, session)
    await require_agent_member_access(agent, auth, session)
    channel_permission(agent, "internal_chat")
    title = payload.title or f"Chat with {agent.name}"
    conversation = ChatConversation(
        department_id=agent.department_id,
        agent_id=agent.id,
        created_by=auth.user_id,
        title=title[:200],
        status="active",
    )
    session.add(conversation)
    await session.flush()
    await session.refresh(conversation, attribute_names=["agent", "messages"])
    await set_conversation_department_context(session, conversation)
    response_data = await conversation_data(conversation, session, include_messages=True)
    await session.commit()
    return {"data": response_data}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    auth: AuthDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    conversation = await get_conversation_or_404(conversation_id, session)
    await set_conversation_department_context(session, conversation)
    return {"data": await conversation_data(conversation, session, include_messages=True)}


@router.post("/conversations/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
async def send_message(
    conversation_id: UUID,
    payload: ChatSendPayload,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
    settings: AppSettings,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    conversation = await get_conversation_or_404(conversation_id, session)
    agent = await get_agent_or_404(conversation.agent_id, session)
    await set_agent_department_context(session, auth, agent)
    await require_agent_member_access(agent, auth, session)
    if conversation.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation is archived.",
        )
    if agent.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Agent must be active before it can be invoked.",
        )
    channel_permission(agent, "internal_chat")
    if not settings.openrouter_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENROUTER_API_KEY is not configured.",
        )

    user_message = ChatMessage(
        conversation_id=conversation.id,
        department_id=conversation.department_id,
        agent_id=conversation.agent_id,
        sender_type="user",
        sender_user_id=auth.user_id,
        content=payload.content,
    )
    session.add(user_message)
    await session.flush()

    history_messages = [
        AgentInvokeMessage(
            role="assistant" if message.sender_type == "assistant" else "user",
            content=message.content,
        )
        for message in conversation.messages[-19:]
        if message.sender_type in {"user", "assistant"}
    ]
    history_messages.append(AgentInvokeMessage(role="user", content=payload.content))

    prompt = active_prompt(agent)
    data_source_context = await build_agent_data_source_context(session, settings, agent)
    system_prompt = prompt.system_prompt
    if data_source_context:
        system_prompt = f"{system_prompt}\n\n{data_source_context}"
    config = active_llm_config(agent)
    estimated_input = estimate_input_tokens(system_prompt, history_messages)
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
        "internal_chat",
        estimated_cost.display_cost_usd,
        estimated_cost.display_cost_thb,
    )

    request_trace_id = uuid4()
    started_at = datetime.now(UTC)
    openrouter_messages = [
        {"role": "system", "content": system_prompt},
        *[message.model_dump() for message in history_messages],
    ]
    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
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
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="OpenRouter request timed out.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenRouter request failed.",
        ) from exc

    if response.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenRouter returned {response.status_code}: {response.text[:500]}",
        )

    body = response.json()
    choices = body.get("choices") or []
    if not choices:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="OpenRouter response did not include choices.",
        )
    answer = choices[0].get("message", {}).get("content") or ""
    assistant_message = ChatMessage(
        conversation_id=conversation.id,
        department_id=conversation.department_id,
        agent_id=conversation.agent_id,
        sender_type="assistant",
        content=answer,
    )
    session.add(assistant_message)
    await session.flush()

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
            conversation_id=conversation.id,
            message_id=assistant_message.id,
        ),
    )
    assistant_message.usage_event_id = UUID(usage_data["id"])
    now = datetime.now(UTC)
    conversation.last_message_at = now
    conversation.updated_at = now
    if conversation.title.startswith("Chat with "):
        conversation.title = payload.content[:60]
    await session.flush()
    await session.refresh(conversation, attribute_names=["agent", "messages"])
    await set_conversation_department_context(session, conversation)
    response_conversation = await conversation_data(conversation, session, include_messages=True)
    response_user_message = message_data(user_message)
    response_assistant_message = message_data(assistant_message)
    await session.commit()
    return {
        "data": {
            "conversation": response_conversation,
            "user_message": response_user_message,
            "assistant_message": response_assistant_message,
            "usage": usage_data,
            "budget": budget.get("budget"),
        }
    }
