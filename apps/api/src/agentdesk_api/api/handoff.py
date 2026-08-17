from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from agentdesk_api.api.agents import (
    get_agent_or_404,
    require_department_agent_manager_access,
    require_department_member_access,
    set_auth_context,
)
from agentdesk_api.api.auth import AuthDependency, CsrfDependency, DbSession
from agentdesk_api.db.models import HandoffCase, HandoffCaseMessage

router = APIRouter(prefix="/handoff", tags=["human-handoff"])


class CaseCreate(BaseModel):
    agent_id: UUID
    conversation_id: UUID | None = None
    requester_contact: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=255)
    reason: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")


class CaseUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|assigned|pending|resolved|closed)$")
    priority: str | None = Field(default=None, pattern="^(low|normal|high|urgent)$")
    assigned_to: UUID | None = None


class CaseMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


def case_data(case: HandoffCase) -> dict[str, object]:
    return {
        "id": str(case.id),
        "department_id": str(case.department_id),
        "agent_id": str(case.agent_id),
        "conversation_id": str(case.conversation_id) if case.conversation_id else None,
        "requester_contact": case.requester_contact,
        "status": case.status,
        "priority": case.priority,
        "subject": case.subject,
        "reason": case.reason,
        "assigned_to": str(case.assigned_to) if case.assigned_to else None,
        "sla_due_at": case.sla_due_at.isoformat() if case.sla_due_at else None,
        "created_at": case.created_at.isoformat(),
        "updated_at": case.updated_at.isoformat(),
    }


@router.get("/departments/{department_id}/cases")
async def list_cases(
    department_id: UUID, auth: AuthDependency, session: DbSession, status_filter: str | None = None
) -> dict[str, object]:
    await set_auth_context(session, auth)
    await require_department_member_access(department_id, auth, session)
    query = (
        select(HandoffCase)
        .where(HandoffCase.department_id == department_id)
        .order_by(HandoffCase.created_at.desc())
    )
    if status_filter:
        query = query.where(HandoffCase.status == status_filter)
    cases = list((await session.scalars(query)).all())
    return {"data": [case_data(case) for case in cases], "meta": {"total": len(cases)}}


@router.post("/departments/{department_id}/cases", status_code=status.HTTP_201_CREATED)
async def create_case(
    department_id: UUID,
    payload: CaseCreate,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    await require_department_member_access(department_id, auth, session)
    agent = await get_agent_or_404(payload.agent_id, session)
    if agent.department_id != department_id:
        raise HTTPException(status_code=404, detail="Agent not found.")
    case = HandoffCase(
        department_id=department_id,
        agent_id=agent.id,
        conversation_id=payload.conversation_id,
        requester_user_id=auth.user_id,
        requester_contact=payload.requester_contact,
        subject=payload.subject,
        reason=payload.reason,
        priority=payload.priority,
        sla_due_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(case)
    await session.flush()
    await session.commit()
    return {"data": case_data(case)}


@router.patch("/cases/{case_id}")
async def update_case(
    case_id: UUID, payload: CaseUpdate, auth: AuthDependency, _: CsrfDependency, session: DbSession
) -> dict[str, object]:
    await set_auth_context(session, auth)
    case = await session.get(HandoffCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Handoff case not found.")
    await require_department_agent_manager_access(case.department_id, auth, session)
    for field in ("status", "priority", "assigned_to"):
        value = getattr(payload, field)
        if value is not None:
            setattr(case, field, value)
    if case.status in {"resolved", "closed"}:
        case.resolved_at = datetime.now(UTC)
    await session.commit()
    return {"data": case_data(case)}


@router.post("/cases/{case_id}/messages", status_code=status.HTTP_201_CREATED)
async def add_case_message(
    case_id: UUID,
    payload: CaseMessageCreate,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_auth_context(session, auth)
    case = await session.get(HandoffCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Handoff case not found.")
    await require_department_member_access(case.department_id, auth, session)
    message = HandoffCaseMessage(
        case_id=case.id,
        sender_user_id=auth.user_id,
        sender_type="staff",
        content=payload.content.strip(),
    )
    session.add(message)
    case.status = "assigned"
    await session.commit()
    return {
        "data": {
            "id": str(message.id),
            "case_id": str(case.id),
            "sender_type": message.sender_type,
            "content": message.content,
            "created_at": message.created_at.isoformat(),
        }
    }
