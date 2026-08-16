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
from agentdesk_api.db.models import Department, DepartmentMembership

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
