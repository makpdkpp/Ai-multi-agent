from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from agentdesk_api.api.agents import require_department_agent_manager_access
from agentdesk_api.api.auth import AuthDependency, CsrfDependency, DbSession, SuperAdminDependency
from agentdesk_api.db.models import DepartmentLlmModelGrant, LlmModel, LlmProvider

router = APIRouter(prefix="/llm-profiles", tags=["llm-profiles"])


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider_type: str = Field(pattern=r"^(openrouter|ollama|vllm|manual)$")
    base_url: str = Field(min_length=1, max_length=500)
    secret_ref: str | None = Field(default=None, max_length=200)


class ModelCreate(BaseModel):
    provider_id: UUID
    model_key: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    input_per_million: Decimal = Field(default=Decimal("0"), ge=0)
    output_per_million: Decimal = Field(default=Decimal("0"), ge=0)


def profile_data(model: LlmModel, granted: bool = False) -> dict[str, object]:
    return {
        "id": str(model.id),
        "provider_id": str(model.provider_id),
        "provider_name": model.provider.name if model.provider else None,
        "provider_type": model.provider.provider_type if model.provider else None,
        "display_name": model.display_name,
        "model_key": model.model_key,
        "status": model.status,
        "granted": granted,
    }


@router.get("")
async def list_profiles(
    auth: AuthDependency,
    session: DbSession,
    department_id: UUID | None = None,
) -> dict[str, object]:
    if department_id is not None and auth.system_role != "super_admin":
        await require_department_agent_manager_access(department_id, auth, session)
    statement = (
        select(LlmModel)
        .join(LlmProvider)
        .options(selectinload(LlmModel.provider))
        .where(LlmModel.status == "active", LlmProvider.status == "active")
        .order_by(LlmProvider.name, LlmModel.display_name)
    )
    if department_id is not None and auth.system_role != "super_admin":
        statement = statement.join(
            DepartmentLlmModelGrant,
            DepartmentLlmModelGrant.model_id == LlmModel.id,
        ).where(
            DepartmentLlmModelGrant.department_id == department_id,
            DepartmentLlmModelGrant.status == "active",
        )
    result = await session.execute(statement)
    models = list(result.scalars())
    granted_ids: set[UUID] = set()
    if department_id is not None:
        grants = await session.execute(
            select(DepartmentLlmModelGrant.model_id).where(
                DepartmentLlmModelGrant.department_id == department_id,
                DepartmentLlmModelGrant.status == "active",
            )
        )
        granted_ids = set(grants.scalars())
    return {"data": [profile_data(model, model.id in granted_ids) for model in models]}


@router.get("/providers")
async def list_providers(auth: SuperAdminDependency, session: DbSession) -> dict[str, object]:
    result = await session.execute(select(LlmProvider).order_by(LlmProvider.name))
    return {
        "data": [
            {
                "id": str(provider.id),
                "name": provider.name,
                "provider_type": provider.provider_type,
                "base_url": provider.base_url,
                "status": provider.status,
            }
            for provider in result.scalars()
        ]
    }


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    payload: ProviderCreate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    provider = LlmProvider(
        name=payload.name.strip(),
        provider_type=payload.provider_type,
        base_url=payload.base_url.rstrip("/"),
        secret_ref=payload.secret_ref,
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return {
        "data": {
            "id": str(provider.id),
            "name": provider.name,
            "provider_type": provider.provider_type,
            "base_url": provider.base_url,
        }
    }


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(
    payload: ModelCreate,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    provider = await session.get(LlmProvider, payload.provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="LLM provider not found.")
    model = LlmModel(
        provider_id=provider.id,
        model_key=payload.model_key.strip(),
        display_name=payload.display_name.strip(),
    )
    session.add(model)
    await session.commit()
    await session.refresh(model, attribute_names=["provider"])
    return {"data": profile_data(model)}


@router.put("/departments/{department_id}/models/{model_id}")
async def grant_model(
    department_id: UUID,
    model_id: UUID,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    model = await session.get(LlmModel, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="LLM model not found.")
    grant = await session.scalar(
        select(DepartmentLlmModelGrant).where(
            DepartmentLlmModelGrant.department_id == department_id,
            DepartmentLlmModelGrant.model_id == model_id,
        )
    )
    if grant is None:
        grant = DepartmentLlmModelGrant(
            department_id=department_id,
            model_id=model_id,
            created_by=auth.user_id,
        )
        session.add(grant)
    else:
        grant.status = "active"
    await session.commit()
    return {
        "data": {
            "department_id": str(department_id),
            "model_id": str(model_id),
            "status": "active",
        }
    }


@router.delete(
    "/departments/{department_id}/models/{model_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_model(
    department_id: UUID,
    model_id: UUID,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> None:
    grant = await session.scalar(
        select(DepartmentLlmModelGrant).where(
            DepartmentLlmModelGrant.department_id == department_id,
            DepartmentLlmModelGrant.model_id == model_id,
        )
    )
    if grant is not None:
        grant.status = "disabled"
        await session.commit()
