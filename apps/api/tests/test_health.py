from fastapi.testclient import TestClient

from agentdesk_api.main import app


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_system_info() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/system/info")

    assert response.status_code == 200
    assert response.json()["phase"] == "foundation"


def test_me_requires_authentication() -> None:
    with TestClient(app) as client:
        response = client.get("/api/v1/me")

    assert response.status_code == 401

