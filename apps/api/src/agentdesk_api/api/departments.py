from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from agentdesk_api.api.auth import CsrfDependency, DbSession, SuperAdminDependency
from agentdesk_api.db.models import Department, DepartmentMembership, User, UserIdentity
from agentdesk_api.security import hash_password, normalized_email

router = APIRouter(prefix="/departments", tags=["departments"])
_code_pattern = re.compile(r"^[a-z][a-z0-9-]{1,49}$")


class DepartmentCreate(BaseModel):
    code: str = Field(min_length=2, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="Asia/Bangkok", min_length=1, max_length=64)
    retention_days: int = Field(default=90, ge=1, le=3650)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _code_pattern.fullmatch(normalized):
            raise ValueError(
                "Code must start with a letter and contain lowercase letters, numbers, or hyphens"
            )
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    retention_days: int | None = Field(default=None, ge=1, le=3650)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class DepartmentView(BaseModel):
    id: UUID
    code: str
    name: str
    timezone: str
    status: str
    retention_days: int
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class DepartmentMemberCreate(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=200)
    role: Literal["department_admin", "agent_manager", "staff", "viewer"] = "staff"
    password: str | None = Field(default=None, min_length=8, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalized_email(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name is required")
        return normalized


class DepartmentMemberUpdate(BaseModel):
    role: Literal["department_admin", "agent_manager", "staff", "viewer"] | None = None
    status: Literal["active", "suspended"] | None = None


class DepartmentMemberView(BaseModel):
    id: UUID
    user_id: UUID
    email: str
    display_name: str
    role: str
    status: str
    user_status: str
    created_at: datetime
    updated_at: datetime


async def set_super_admin_context(session: DbSession, role: str) -> None:
    await session.execute(text("SELECT set_config('app.system_role', :role, true)"), {"role": role})


def department_data(department: Department, member_count: int = 0) -> dict[str, object]:
    return DepartmentView(
        id=department.id,
        code=department.code,
        name=department.name,
        timezone=department.timezone,
        status=department.status,
        retention_days=department.retention_days,
        member_count=member_count,
        created_at=department.created_at,
        updated_at=department.updated_at,
    ).model_dump(mode="json")


def member_data(membership: DepartmentMembership, user: User) -> dict[str, object]:
    return DepartmentMemberView(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=membership.role,
        status=membership.status,
        user_status=user.status,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    ).model_dump(mode="json")


def membership_conflict_detail(exc: IntegrityError) -> str:
    constraint_name = getattr(getattr(exc, "orig", None), "constraint_name", "")
    if constraint_name == "uq_membership_department_user":
        return "User is already a member of this department."
    if "role" in constraint_name:
        return "Invalid department member role."
    if "status" in constraint_name:
        return "Invalid department member status."
    if constraint_name == "uq_users_email":
        return "A user with this email already exists."
    return "Unable to create department member."


@router.get("")
async def list_departments(auth: SuperAdminDependency, session: DbSession) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    result = await session.execute(
        select(Department, func.count(DepartmentMembership.id))
        .outerjoin(DepartmentMembership)
        .where(Department.deleted_at.is_(None))
        .group_by(Department.id)
        .order_by(Department.name)
    )
    rows = result.all()
    return {
        "data": [department_data(department, count) for department, count in rows],
        "meta": {"total": len(rows)},
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_department(
    payload: DepartmentCreate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    department = Department(**payload.model_dump(), status="active")
    session.add(department)
    try:
        await session.flush()
        response_data = department_data(department)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department code already exists.",
        ) from exc
    return {"data": response_data}


async def get_department_or_404(department_id: UUID, session: DbSession) -> Department:
    department = await session.scalar(
        select(Department).where(Department.id == department_id, Department.deleted_at.is_(None))
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")
    return department


@router.get("/{department_id}")
async def get_department(
    department_id: UUID, auth: SuperAdminDependency, session: DbSession
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    department = await get_department_or_404(department_id, session)
    member_count = await session.scalar(
        select(func.count(DepartmentMembership.id)).where(
            DepartmentMembership.department_id == department.id
        )
    )
    return {"data": department_data(department, member_count or 0)}


@router.patch("/{department_id}")
async def update_department(
    department_id: UUID,
    payload: DepartmentUpdate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    department = await get_department_or_404(department_id, session)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(department, field, value)
    department.updated_at = datetime.now(UTC)
    await session.flush()
    response_data = department_data(department)
    await session.commit()
    return {"data": response_data}


async def change_status(
    department_id: UUID,
    new_status: Literal["active", "suspended"],
    auth: SuperAdminDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    department = await get_department_or_404(department_id, session)
    department.status = new_status
    department.updated_at = datetime.now(UTC)
    await session.flush()
    response_data = department_data(department)
    await session.commit()
    return {"data": response_data}


@router.post("/{department_id}/suspend")
async def suspend_department(
    department_id: UUID, auth: SuperAdminDependency, _: CsrfDependency, session: DbSession
) -> dict[str, object]:
    return await change_status(department_id, "suspended", auth, session)


@router.post("/{department_id}/resume")
async def resume_department(
    department_id: UUID, auth: SuperAdminDependency, _: CsrfDependency, session: DbSession
) -> dict[str, object]:
    return await change_status(department_id, "active", auth, session)


@router.get("/{department_id}/members")
async def list_department_members(
    department_id: UUID,
    auth: SuperAdminDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    await get_department_or_404(department_id, session)
    result = await session.execute(
        select(DepartmentMembership, User)
        .join(User, User.id == DepartmentMembership.user_id)
        .where(DepartmentMembership.department_id == department_id)
        .order_by(User.display_name)
    )
    rows = result.all()
    return {
        "data": [member_data(membership, user) for membership, user in rows],
        "meta": {"total": len(rows)},
    }


@router.post("/{department_id}/members", status_code=status.HTTP_201_CREATED)
async def create_department_member(
    department_id: UUID,
    payload: DepartmentMemberCreate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    await get_department_or_404(department_id, session)
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None:
        user_status = "active" if payload.password else "invited"
        user = User(
            email=payload.email,
            display_name=payload.display_name,
            system_role="standard_user",
            status=user_status,
        )
        identity = UserIdentity(
            user=user,
            provider_type="local",
            provider_subject=payload.email,
            email_at_link_time=payload.email,
            password_hash=hash_password(payload.password) if payload.password else None,
            password_changed_at=datetime.now(UTC) if payload.password else None,
            status="active" if payload.password else "pending_activation",
        )
        session.add_all([user, identity])
    else:
        user.display_name = payload.display_name

    membership = DepartmentMembership(
        department_id=department_id,
        user=user,
        role=payload.role,
        status="active",
    )
    session.add(membership)
    try:
        await session.flush()
        response_data = member_data(membership, user)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=membership_conflict_detail(exc),
        ) from exc
    return {"data": response_data}


async def get_membership_or_404(
    department_id: UUID,
    membership_id: UUID,
    session: DbSession,
) -> tuple[DepartmentMembership, User]:
    result = await session.execute(
        select(DepartmentMembership, User)
        .join(User, User.id == DepartmentMembership.user_id)
        .where(
            DepartmentMembership.id == membership_id,
            DepartmentMembership.department_id == department_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found.")
    return row


@router.patch("/{department_id}/members/{membership_id}")
async def update_department_member(
    department_id: UUID,
    membership_id: UUID,
    payload: DepartmentMemberUpdate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_super_admin_context(session, auth.system_role)
    await get_department_or_404(department_id, session)
    membership, user = await get_membership_or_404(department_id, membership_id, session)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(membership, field, value)
    membership.updated_at = datetime.now(UTC)
    await session.flush()
    response_data = member_data(membership, user)
    await session.commit()
    return {"data": response_data}
