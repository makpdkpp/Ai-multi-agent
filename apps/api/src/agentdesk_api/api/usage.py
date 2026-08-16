from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from agentdesk_api.api.auth import (
    AppSettings,
    AuthContext,
    AuthDependency,
    CsrfDependency,
    DbSession,
    SuperAdminDependency,
)
from agentdesk_api.config import Settings
from agentdesk_api.db.models import (
    Department,
    DepartmentBudget,
    DepartmentMembership,
    ExchangeRate,
    LlmModel,
    LlmProvider,
    LlmUsageEvent,
    ModelPricingVersion,
)

router = APIRouter(tags=["usage"])
MONEY_QUANT = Decimal("0.00000001")
MILLION = Decimal("1000000")


class BudgetPayload(BaseModel):
    currency: Literal["USD", "THB"] = "THB"
    limit_amount: Decimal = Field(ge=Decimal("0"))
    period_type: Literal["monthly"] = "monthly"
    period_start_day: int = Field(default=1, ge=1, le=28)
    action_on_exceed: Literal["notify_only", "pause_public_widget", "pause_all_llm"] = (
        "notify_only"
    )
    warning_thresholds: list[int] = Field(default_factory=lambda: [70, 90, 100])
    enabled: bool = True

    @field_validator("warning_thresholds")
    @classmethod
    def validate_thresholds(cls, value: list[int]) -> list[int]:
        normalized = sorted(set(value))
        if not normalized or any(item < 1 or item > 100 for item in normalized):
            raise ValueError("warning_thresholds must contain values from 1 to 100")
        return normalized


class ManualRatePayload(BaseModel):
    rate: Decimal = Field(gt=Decimal("0"))
    source: str = Field(default="manual_fallback", min_length=1, max_length=100)
    effective_at: datetime | None = None


class UsageEventPayload(BaseModel):
    department_id: UUID
    usage_type: Literal[
        "coordinator",
        "sql_agent",
        "rag_agent",
        "excel_agent",
        "answer_synthesis",
        "handoff_classification",
        "agent_reply_draft",
        "conversation_summary",
    ]
    model_key: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    provider_type: Literal["openrouter", "ollama", "vllm", "manual"] = "openrouter"
    provider_name: str = Field(default="OpenRouter", min_length=1, max_length=100)
    base_url: str = Field(default="https://openrouter.ai/api/v1", min_length=1)
    request_trace_id: UUID = Field(default_factory=uuid4)
    agent_id: UUID | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    parent_event_id: UUID | None = None
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cached_input_tokens: int = Field(default=0, ge=0)
    input_per_million: Decimal = Field(ge=Decimal("0"))
    output_per_million: Decimal = Field(ge=Decimal("0"))
    cached_input_per_million: Decimal | None = Field(default=None, ge=Decimal("0"))
    infrastructure_cost_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))
    exchange_rate: Decimal | None = Field(default=None, gt=Decimal("0"))
    latency_ms: int | None = Field(default=None, ge=0)
    status: Literal["succeeded", "failed", "cancelled"] = "succeeded"
    provider_request_id: str | None = Field(default=None, max_length=255)

    @field_validator("cached_input_tokens")
    @classmethod
    def cached_tokens_cannot_exceed_input(cls, value: int, info) -> int:
        input_tokens = info.data.get("input_tokens")
        if input_tokens is not None and value > input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        return value


@dataclass(frozen=True)
class CostBreakdown:
    provider_cost_usd: Decimal
    display_cost_usd: Decimal
    display_cost_thb: Decimal
    pricing_snapshot: dict[str, str]


async def set_system_context(session: AsyncSession, auth: AuthContext) -> None:
    await session.execute(
        text("SELECT set_config('app.system_role', :role, true)"),
        {"role": auth.system_role},
    )
    await session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": str(auth.user_id)},
    )


async def require_department_admin(
    department_id: UUID,
    auth: AuthContext,
    session: AsyncSession,
) -> None:
    await set_system_context(session, auth)
    if auth.system_role == "super_admin":
        await session.execute(
            text("SELECT set_config('app.department_id', :department_id, true)"),
            {"department_id": str(department_id)},
        )
        return
    membership = await session.scalar(
        select(DepartmentMembership).where(
            DepartmentMembership.department_id == department_id,
            DepartmentMembership.user_id == auth.user_id,
            DepartmentMembership.status == "active",
            DepartmentMembership.role.in_(("owner", "admin")),
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")
    await session.execute(
        text("SELECT set_config('app.department_id', :department_id, true)"),
        {"department_id": str(department_id)},
    )


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def calculate_cost(payload: UsageEventPayload, exchange_rate: Decimal) -> CostBreakdown:
    cached_price = payload.cached_input_per_million or payload.input_per_million
    billable_input_tokens = payload.input_tokens - payload.cached_input_tokens
    input_cost = Decimal(billable_input_tokens) * payload.input_per_million / MILLION
    cached_cost = Decimal(payload.cached_input_tokens) * cached_price / MILLION
    output_cost = Decimal(payload.output_tokens) * payload.output_per_million / MILLION
    provider_cost = money(input_cost + cached_cost + output_cost)
    display_usd = money(provider_cost + payload.infrastructure_cost_usd)
    display_thb = money(display_usd * exchange_rate)
    return CostBreakdown(
        provider_cost_usd=provider_cost,
        display_cost_usd=display_usd,
        display_cost_thb=display_thb,
        pricing_snapshot={
            "currency": "USD",
            "input_per_million": str(money(payload.input_per_million)),
            "output_per_million": str(money(payload.output_per_million)),
            "cached_input_per_million": str(money(cached_price)),
        },
    )


async def latest_exchange_rate(session: AsyncSession) -> ExchangeRate:
    rate = await session.scalar(
        select(ExchangeRate)
        .where(ExchangeRate.base_currency == "USD", ExchangeRate.quote_currency == "THB")
        .order_by(ExchangeRate.effective_at.desc())
        .limit(1)
    )
    if rate is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No USDTHB rate.",
        )
    return rate


async def fetch_exchange_rate_from_provider(
    session: AsyncSession,
    settings: Settings,
) -> ExchangeRate:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(settings.exchange_rate_api_url)
    response.raise_for_status()
    payload = response.json()
    rate_value = payload.get("rates", {}).get("THB")
    if payload.get("result") != "success" or payload.get("base_code") != "USD" or not rate_value:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Invalid exchange rate response.",
        )
    effective_unix = payload.get("time_last_update_unix")
    rate = ExchangeRate(
        base_currency="USD",
        quote_currency="THB",
        rate=Decimal(str(rate_value)),
        source="ExchangeRate-API",
        effective_at=datetime.fromtimestamp(effective_unix, UTC)
        if effective_unix
        else datetime.now(UTC),
        fetched_at=datetime.now(UTC),
        status="live",
    )
    session.add(rate)
    await session.flush()
    return rate


async def refresh_exchange_rate_if_stale(
    session: AsyncSession,
    settings: Settings,
) -> ExchangeRate | None:
    current = await session.scalar(
        select(ExchangeRate)
        .where(ExchangeRate.base_currency == "USD", ExchangeRate.quote_currency == "THB")
        .order_by(ExchangeRate.fetched_at.desc())
        .limit(1)
    )
    if current is not None:
        min_age = timedelta(seconds=settings.exchange_rate_min_refresh_seconds)
        if current.fetched_at > datetime.now(UTC) - min_age:
            return current
    return await fetch_exchange_rate_from_provider(session, settings)


async def get_or_create_provider(session: AsyncSession, payload: UsageEventPayload) -> LlmProvider:
    provider = await session.scalar(
        select(LlmProvider).where(
            LlmProvider.provider_type == payload.provider_type,
            LlmProvider.name == payload.provider_name,
        )
    )
    if provider is not None:
        return provider
    provider = LlmProvider(
        provider_type=payload.provider_type,
        name=payload.provider_name,
        base_url=payload.base_url,
        status="active",
    )
    session.add(provider)
    await session.flush()
    return provider


async def get_or_create_model(
    session: AsyncSession,
    provider: LlmProvider,
    payload: UsageEventPayload,
) -> LlmModel:
    model = await session.scalar(
        select(LlmModel).where(
            LlmModel.provider_id == provider.id,
            LlmModel.model_key == payload.model_key,
        )
    )
    if model is not None:
        return model
    model = LlmModel(
        provider_id=provider.id,
        model_key=payload.model_key,
        display_name=payload.display_name or payload.model_key,
        status="active",
    )
    session.add(model)
    await session.flush()
    return model


async def get_or_create_pricing(
    session: AsyncSession,
    model: LlmModel,
    payload: UsageEventPayload,
) -> ModelPricingVersion:
    pricing = await session.scalar(
        select(ModelPricingVersion)
        .where(
            ModelPricingVersion.model_id == model.id,
            ModelPricingVersion.currency == "USD",
            ModelPricingVersion.input_per_million == payload.input_per_million,
            ModelPricingVersion.output_per_million == payload.output_per_million,
            ModelPricingVersion.cached_input_per_million == payload.cached_input_per_million,
            ModelPricingVersion.effective_to.is_(None),
        )
        .order_by(ModelPricingVersion.effective_from.desc())
        .limit(1)
    )
    if pricing is not None:
        return pricing
    pricing = ModelPricingVersion(
        model_id=model.id,
        currency="USD",
        input_per_million=payload.input_per_million,
        output_per_million=payload.output_per_million,
        cached_input_per_million=payload.cached_input_per_million,
        effective_from=datetime.now(UTC),
        source="usage_event_snapshot",
    )
    session.add(pricing)
    await session.flush()
    return pricing


def rate_data(rate: ExchangeRate) -> dict[str, object]:
    return {
        "base_currency": rate.base_currency,
        "quote_currency": rate.quote_currency,
        "rate": str(money(rate.rate)),
        "source": rate.source,
        "effective_at": rate.effective_at.isoformat(),
        "fetched_at": rate.fetched_at.isoformat(),
        "status": rate.status,
    }


def budget_data(
    budget: DepartmentBudget | None,
    spent_usd: Decimal,
    spent_thb: Decimal,
) -> dict[str, object] | None:
    if budget is None:
        return None
    spent = spent_thb if budget.currency == "THB" else spent_usd
    percent = (
        Decimal("0")
        if budget.limit_amount == 0
        else spent * Decimal("100") / budget.limit_amount
    )
    return {
        "currency": budget.currency,
        "limit_amount": str(money(budget.limit_amount)),
        "spent_amount": str(money(spent)),
        "percent_used": str(money(percent)),
        "period_type": budget.period_type,
        "period_start_day": budget.period_start_day,
        "action_on_exceed": budget.action_on_exceed,
        "warning_thresholds": budget.warning_thresholds,
        "enabled": budget.enabled,
    }


async def usage_summary(
    session: AsyncSession,
    from_date: datetime | None,
    to_date: datetime | None,
    department_id: UUID | None = None,
) -> dict[str, object]:
    conditions = []
    if department_id is not None:
        conditions.append(LlmUsageEvent.department_id == department_id)
    if from_date is not None:
        conditions.append(LlmUsageEvent.created_at >= from_date)
    if to_date is not None:
        conditions.append(LlmUsageEvent.created_at < to_date)
    statement = select(
        func.coalesce(func.sum(LlmUsageEvent.input_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.output_tokens), 0),
        func.coalesce(func.sum(LlmUsageEvent.cached_input_tokens), 0),
        func.count(LlmUsageEvent.id),
        func.coalesce(func.sum(LlmUsageEvent.provider_cost_usd), 0),
        func.coalesce(func.sum(LlmUsageEvent.infrastructure_cost_usd), 0),
        func.coalesce(func.sum(LlmUsageEvent.display_cost_usd), 0),
        func.coalesce(func.sum(LlmUsageEvent.display_cost_thb), 0),
    )
    if conditions:
        statement = statement.where(*conditions)
    row = (await session.execute(statement)).one()
    spent_usd = money(Decimal(row[6]))
    spent_thb = money(Decimal(row[7]))
    latest_rate = await latest_exchange_rate(session)
    budget = None
    if department_id is not None:
        budget = await session.scalar(
            select(DepartmentBudget).where(
                DepartmentBudget.department_id == department_id,
                DepartmentBudget.period_type == "monthly",
            )
        )
    return {
        "period": {
            "from": from_date.isoformat() if from_date else None,
            "to": to_date.isoformat() if to_date else None,
        },
        "input_tokens": int(row[0]),
        "output_tokens": int(row[1]),
        "cached_input_tokens": int(row[2]),
        "requests": int(row[3]),
        "provider_cost_usd": str(money(Decimal(row[4]))),
        "infrastructure_cost_usd": str(money(Decimal(row[5]))),
        "display_cost_usd": str(spent_usd),
        "display_cost_thb": str(spent_thb),
        "exchange_rate": rate_data(latest_rate),
        "budget": budget_data(budget, spent_usd, spent_thb),
    }


@router.get("/system/exchange-rates/latest")
async def get_latest_exchange_rate(
    auth: SuperAdminDependency,
    session: DbSession,
    pair: str = Query(default="USDTHB", pattern="^USDTHB$"),
) -> dict[str, object]:
    await set_system_context(session, auth)
    rate = await latest_exchange_rate(session)
    return {"data": rate_data(rate), "meta": {"pair": pair}}


@router.put("/system/exchange-rates/fallback")
async def set_exchange_rate_fallback(
    payload: ManualRatePayload,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_system_context(session, auth)
    rate = ExchangeRate(
        base_currency="USD",
        quote_currency="THB",
        rate=payload.rate,
        source=payload.source,
        effective_at=payload.effective_at or datetime.now(UTC),
        fetched_at=datetime.now(UTC),
        status="manual_fallback",
    )
    session.add(rate)
    await session.commit()
    return {"data": rate_data(rate)}


@router.post("/system/exchange-rates/sync")
async def sync_exchange_rate(
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
    settings: AppSettings,
) -> dict[str, object]:
    await set_system_context(session, auth)
    rate = await fetch_exchange_rate_from_provider(session, settings)
    await session.commit()
    return {"data": rate_data(rate)}


@router.get("/system/usage/summary")
async def get_system_usage_summary(
    auth: SuperAdminDependency,
    session: DbSession,
    from_date: Annotated[datetime | None, Query(alias="from")] = None,
    to_date: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict[str, object]:
    await set_system_context(session, auth)
    return {"data": await usage_summary(session, from_date, to_date)}


@router.post("/system/usage/events", status_code=status.HTTP_201_CREATED)
async def record_usage_event(
    payload: UsageEventPayload,
    auth: SuperAdminDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await set_system_context(session, auth)
    department = await session.scalar(
        select(Department).where(
            Department.id == payload.department_id,
            Department.deleted_at.is_(None),
        )
    )
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found.")
    await session.execute(
        text("SELECT set_config('app.department_id', :department_id, true)"),
        {"department_id": str(payload.department_id)},
    )
    rate = await latest_exchange_rate(session)
    exchange_snapshot = payload.exchange_rate or rate.rate
    provider = await get_or_create_provider(session, payload)
    model = await get_or_create_model(session, provider, payload)
    pricing = await get_or_create_pricing(session, model, payload)
    cost = calculate_cost(payload, exchange_snapshot)
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
        exchange_rate_snapshot=money(exchange_snapshot),
        pricing_snapshot=cost.pricing_snapshot,
        latency_ms=payload.latency_ms,
        status=payload.status,
        provider_request_id=payload.provider_request_id,
    )
    session.add(event)
    await session.commit()
    return {
        "data": {
            "id": str(event.id),
            "request_trace_id": str(event.request_trace_id),
            "provider_cost_usd": str(cost.provider_cost_usd),
            "display_cost_usd": str(cost.display_cost_usd),
            "display_cost_thb": str(cost.display_cost_thb),
            "exchange_rate_snapshot": str(money(exchange_snapshot)),
        }
    }


@router.get("/departments/{department_id}/usage/summary")
async def get_department_usage_summary(
    department_id: UUID,
    auth: AuthDependency,
    session: DbSession,
    from_date: Annotated[datetime | None, Query(alias="from")] = None,
    to_date: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict[str, object]:
    await require_department_admin(department_id, auth, session)
    return {"data": await usage_summary(session, from_date, to_date, department_id)}


@router.get("/departments/{department_id}/budget")
async def get_department_budget(
    department_id: UUID,
    auth: AuthDependency,
    session: DbSession,
) -> dict[str, object]:
    await require_department_admin(department_id, auth, session)
    budget = await session.scalar(
        select(DepartmentBudget).where(
            DepartmentBudget.department_id == department_id,
            DepartmentBudget.period_type == "monthly",
        )
    )
    summary = await usage_summary(session, None, None, department_id)
    return {
        "data": budget_data(
            budget,
            Decimal(summary["display_cost_usd"]),
            Decimal(summary["display_cost_thb"]),
        )
    }


@router.put("/departments/{department_id}/budget")
async def put_department_budget(
    department_id: UUID,
    payload: BudgetPayload,
    auth: AuthDependency,
    _: CsrfDependency,
    session: DbSession,
) -> dict[str, object]:
    await require_department_admin(department_id, auth, session)
    budget = await session.scalar(
        select(DepartmentBudget).where(
            DepartmentBudget.department_id == department_id,
            DepartmentBudget.period_type == payload.period_type,
        )
    )
    if budget is None:
        budget = DepartmentBudget(department_id=department_id)
        session.add(budget)
    budget.currency = payload.currency
    budget.limit_amount = payload.limit_amount
    budget.period_type = payload.period_type
    budget.period_start_day = payload.period_start_day
    budget.action_on_exceed = payload.action_on_exceed
    budget.warning_thresholds = payload.warning_thresholds
    budget.enabled = payload.enabled
    await session.flush()
    summary = await usage_summary(session, None, None, department_id)
    response_data = budget_data(
        budget,
        Decimal(summary["display_cost_usd"]),
        Decimal(summary["display_cost_thb"]),
    )
    await session.commit()
    return {"data": response_data}
