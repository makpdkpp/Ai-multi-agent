import pytest

from agentdesk_api.api.auth import LoginRequest
from agentdesk_api.security import hash_password, normalized_email, token_digest, verify_password


def test_password_round_trip() -> None:
    password_hash = hash_password("a-long-test-password")

    assert verify_password("a-long-test-password", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_tokens_are_stored_as_digests() -> None:
    assert token_digest("secret-token") != "secret-token"
    assert len(token_digest("secret-token")) == 64


def test_email_is_normalized() -> None:
    assert normalized_email("  USER@Example.COM ") == "user@example.com"


def test_internal_local_email_is_accepted_for_login() -> None:
    payload = LoginRequest(email="Admin@Company.Local", password="test")

    assert payload.email == "admin@company.local"


@pytest.mark.parametrize("email", ["missing-at", "a@@company.local", "a@-company.local"])
def test_invalid_internal_email_is_rejected(email: str) -> None:
    with pytest.raises(ValueError):
        LoginRequest(email=email, password="test")
