from decimal import Decimal

import pytest
from pydantic import ValidationError

from agentdesk_api.api.agents import (
    AgentCreate,
    AgentInvokePayload,
    AgentLlmConfigPayload,
    ChannelPermissionPayload,
    estimate_input_tokens,
)
from agentdesk_api.api.departments import DepartmentMemberCreate


def test_agent_create_normalizes_slug_and_requires_internal_chat() -> None:
    agent = AgentCreate(
        slug=" Sales-Support ",
        name="Sales Support",
        system_prompt=" ตอบคำถามจากข้อมูลฝ่ายขาย ",
        permissions=[ChannelPermissionPayload(channel="internal_chat", enabled=True)],
    )

    assert agent.slug == "sales-support"
    assert agent.system_prompt == "ตอบคำถามจากข้อมูลฝ่ายขาย"


@pytest.mark.parametrize("slug", ["1sales", "sales_team", "s", "Sales Team"])
def test_agent_rejects_invalid_slug(slug: str) -> None:
    with pytest.raises(ValidationError):
        AgentCreate(slug=slug, name="Sales", system_prompt="Answer questions")


def test_agent_rejects_duplicate_channels() -> None:
    with pytest.raises(ValidationError):
        AgentCreate(
            slug="sales-bot",
            name="Sales Bot",
            system_prompt="Answer questions",
            permissions=[
                ChannelPermissionPayload(channel="internal_chat", enabled=True),
                ChannelPermissionPayload(channel="internal_chat", enabled=False),
            ],
        )


def test_agent_rejects_public_only_for_mvp() -> None:
    with pytest.raises(ValidationError):
        AgentCreate(
            slug="sales-bot",
            name="Sales Bot",
            system_prompt="Answer questions",
            permissions=[ChannelPermissionPayload(channel="public_widget", enabled=True)],
        )


def test_llm_config_bounds() -> None:
    config = AgentLlmConfigPayload(
        model_key=" openai/gpt-4o-mini ",
        temperature=Decimal("0.70"),
        top_p=Decimal("0.90"),
        max_output_tokens=2048,
        input_per_million=Decimal("0.20000000"),
        output_per_million=Decimal("0.80000000"),
    )

    assert config.model_key == "openai/gpt-4o-mini"
    assert config.temperature == Decimal("0.70")
    assert config.input_per_million == Decimal("0.20000000")


def test_invoke_payload_requires_user_last_message() -> None:
    with pytest.raises(ValidationError):
        AgentInvokePayload(messages=[{"role": "assistant", "content": "สวัสดี"}])


def test_estimate_input_tokens_includes_system_prompt_and_messages() -> None:
    payload = AgentInvokePayload(messages=[{"role": "user", "content": "12345678"}])

    assert estimate_input_tokens("1234", payload.messages) == 3


def test_department_member_normalizes_email_and_name() -> None:
    member = DepartmentMemberCreate(
        email=" User@Company.Local ",
        display_name=" คุณเมธา ",
        role="staff",
        password="temporary-password",
    )

    assert member.email == "user@company.local"
    assert member.display_name == "คุณเมธา"
