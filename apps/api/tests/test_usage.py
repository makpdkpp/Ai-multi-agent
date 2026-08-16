from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentdesk_api.api.usage import BudgetPayload, UsageEventPayload, calculate_cost


def test_usage_cost_calculation_supports_cached_tokens_and_thb() -> None:
    payload = UsageEventPayload(
        department_id="00000000-0000-0000-0000-000000000001",
        usage_type="answer_synthesis",
        model_key="openai/gpt-4o-mini",
        input_tokens=1_000_000,
        cached_input_tokens=250_000,
        output_tokens=100_000,
        input_per_million=Decimal("0.15000000"),
        cached_input_per_million=Decimal("0.07500000"),
        output_per_million=Decimal("0.60000000"),
        infrastructure_cost_usd=Decimal("0.01000000"),
    )

    cost = calculate_cost(payload, Decimal("35.50000000"))

    assert cost.provider_cost_usd == Decimal("0.19125000")
    assert cost.display_cost_usd == Decimal("0.20125000")
    assert cost.display_cost_thb == Decimal("7.14437500")


def test_usage_rejects_cached_tokens_greater_than_input_tokens() -> None:
    with pytest.raises(ValidationError):
        UsageEventPayload(
            department_id="00000000-0000-0000-0000-000000000001",
            usage_type="coordinator",
            model_key="openai/gpt-4o-mini",
            input_tokens=10,
            cached_input_tokens=11,
            output_tokens=5,
            input_per_million=Decimal("0.15000000"),
            output_per_million=Decimal("0.60000000"),
        )


def test_budget_thresholds_are_sorted_unique_values() -> None:
    budget = BudgetPayload(limit_amount=Decimal("5000.00000000"), warning_thresholds=[90, 70, 90])

    assert budget.warning_thresholds == [70, 90]
