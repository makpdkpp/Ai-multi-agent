from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from agentdesk_api.api.agents import get_agent_or_404
from agentdesk_api.api.auth import AppSettings, DbSession
from agentdesk_api.db.models import AgentPermission, WidgetSession
from agentdesk_api.security import generate_token, token_digest

router = APIRouter(prefix="/public/widgets", tags=["public-widget"])


class WidgetSessionRequest(BaseModel):
    contact: str | None = Field(default=None, max_length=255)


@router.get("/{agent_id}/config")
async def widget_config(agent_id: UUID, session: DbSession) -> dict[str, object]:
    agent = await get_agent_or_404(agent_id, session)
    permission = await session.scalar(
        select(AgentPermission).where(
            AgentPermission.agent_id == agent.id,
            AgentPermission.channel == "public_widget",
            AgentPermission.enabled.is_(True),
        )
    )
    if permission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Public widget is disabled."
        )
    return {
        "data": {
            "agent_id": str(agent.id),
            "name": agent.name,
            "department_id": str(agent.department_id),
            "anonymous": permission.allow_anonymous,
        }
    }


@router.post("/{agent_id}/sessions", status_code=status.HTTP_201_CREATED)
async def create_widget_session(
    agent_id: UUID,
    payload: WidgetSessionRequest,
    request: Request,
    session: DbSession,
    settings: AppSettings,
    origin: str | None = Header(default=None),
) -> dict[str, object]:
    agent = await get_agent_or_404(agent_id, session)
    permission = await session.scalar(
        select(AgentPermission).where(
            AgentPermission.agent_id == agent.id,
            AgentPermission.channel == "public_widget",
            AgentPermission.enabled.is_(True),
        )
    )
    if permission is None or not permission.allow_anonymous:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public widget is not enabled for anonymous use.",
        )
    raw_token = generate_token()
    item = WidgetSession(
        department_id=agent.department_id,
        agent_id=agent.id,
        token_hash=token_digest(raw_token),
        origin=origin or request.headers.get("origin"),
        contact=payload.contact,
        expires_at=datetime.now(UTC) + timedelta(hours=8),
    )
    session.add(item)
    await session.commit()
    return {
        "data": {
            "session_token": raw_token,
            "expires_at": item.expires_at.isoformat(),
            "agent_id": str(agent.id),
        }
    }
