from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from redis.asyncio import Redis
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from agentdesk_api.config import Settings, get_settings
from agentdesk_api.db.models import (
    AuthSession,
    Department,
    DepartmentMembership,
    User,
    UserIdentity,
)
from agentdesk_api.db.session import get_db_session
from agentdesk_api.security import (
    generate_token,
    normalized_email,
    secure_equals,
    token_digest,
    verify_password,
)

router = APIRouter(prefix="/auth/local", tags=["authentication"])
me_router = APIRouter(tags=["authentication"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalized_email(value)


@dataclass(frozen=True)
class AuthContext:
    session_id: UUID
    user_id: UUID
    system_role: str
    csrf_token_hash: str


async def _rate_limit_key(request: Request, email: str, settings: Settings) -> tuple[Redis, str]:
    ip = request.client.host if request.client else "unknown"
    subject = hashlib.sha256(f"{settings.app_secret_key}:{ip}:{email}".encode()).hexdigest()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return redis, f"auth:login:{subject}"


async def _record_login_attempt(redis: Redis, key: str, settings: Settings) -> None:
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, settings.login_attempt_window_seconds)
    if attempts > settings.login_attempt_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.login_attempt_window_seconds)},
        )


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: DbSession,
    settings: AppSettings,
) -> dict[str, object]:
    email = payload.email
    redis, rate_key = await _rate_limit_key(request, email, settings)
    try:
        await _record_login_attempt(redis, rate_key, settings)
        result = await session.execute(
            select(UserIdentity, User)
            .join(User, User.id == UserIdentity.user_id)
            .where(
                UserIdentity.provider_type == "local",
                UserIdentity.provider_subject == email,
            )
        )
        row = result.one_or_none()
        identity, user = row if row else (None, None)
        password_valid = verify_password(
            payload.password,
            identity.password_hash if identity else None,
        )
        account_active = bool(
            identity
            and user
            and identity.status == "active"
            and user.status == "active"
        )
        if not password_valid or not account_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        raw_session_token = generate_token()
        raw_csrf_token = generate_token()
        expires_at = datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours)
        auth_session = AuthSession(
            user_id=user.id,
            identity_id=identity.id,
            token_hash=token_digest(raw_session_token),
            csrf_token_hash=token_digest(raw_csrf_token),
            ip_hash=hashlib.sha256(
                (request.client.host if request.client else "unknown").encode()
            ).hexdigest(),
            user_agent=request.headers.get("user-agent", "")[:1000],
            expires_at=expires_at,
        )
        session.add(auth_session)
        user.last_login_at = datetime.now(UTC)
        identity.last_login_at = datetime.now(UTC)
        await session.commit()
        await redis.delete(rate_key)

        response.set_cookie(
            settings.session_cookie_name,
            raw_session_token,
            max_age=settings.session_ttl_hours * 3600,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        response.set_cookie(
            settings.csrf_cookie_name,
            raw_csrf_token,
            max_age=settings.session_ttl_hours * 3600,
            httponly=False,
            secure=settings.secure_cookies,
            samesite="lax",
            path="/",
        )
        return {
            "data": {
                "user": {
                    "id": str(user.id),
                    "email": user.email,
                    "display_name": user.display_name,
                    "system_role": user.system_role,
                },
                "csrf_token": raw_csrf_token,
                "expires_at": expires_at.isoformat(),
            }
        }
    finally:
        await redis.aclose()


async def require_auth(
    session: DbSession,
    session_token: Annotated[str | None, Cookie(alias="agentdesk_session")] = None,
) -> AuthContext:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )
    result = await session.execute(
        select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == token_digest(session_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > datetime.now(UTC),
            User.status == "active",
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")
    auth_session, user = row
    return AuthContext(auth_session.id, user.id, user.system_role, auth_session.csrf_token_hash)


AuthDependency = Annotated[AuthContext, Depends(require_auth)]


async def require_super_admin(auth: AuthDependency) -> AuthContext:
    if auth.system_role != "super_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super Admin required.")
    return auth


SuperAdminDependency = Annotated[AuthContext, Depends(require_super_admin)]


async def require_csrf(
    auth: AuthDependency,
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if not csrf_token or not secure_equals(token_digest(csrf_token), auth.csrf_token_hash):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid CSRF token.")
    return auth


CsrfDependency = Annotated[AuthContext, Depends(require_csrf)]


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    auth: CsrfDependency,
    session: DbSession,
    settings: AppSettings,
) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.id == auth.session_id)
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@me_router.get("/me")
async def me(
    auth: AuthDependency,
    session: DbSession,
) -> dict[str, object]:
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(auth.user_id)},
    )
    await session.execute(
        text("SELECT set_config('app.system_role', :role, true)"),
        {"role": auth.system_role},
    )
    user = await session.get(User, auth.user_id)
    memberships = await session.execute(
        select(DepartmentMembership, Department)
        .join(Department, Department.id == DepartmentMembership.department_id)
        .where(DepartmentMembership.user_id == auth.user_id)
        .order_by(Department.name)
    )
    return {
        "data": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "system_role": user.system_role,
            "memberships": [
                {
                    "department_id": str(department.id),
                    "department_name": department.name,
                    "role": membership.role,
                }
                for membership, department in memberships.all()
            ],
        }
    }
