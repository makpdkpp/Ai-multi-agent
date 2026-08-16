from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "AgentDesk API"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_secret_key: str = Field(
        default="replace-with-at-least-32-random-characters",
        min_length=32,
    )
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://agentdesk_app:change-me-app@localhost:5432/agentdesk"
    redis_url: str = "redis://:change-me-redis@localhost:6379/0"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "agentdesk_minio"
    s3_secret_key: str = "change-me-minio"
    s3_bucket: str = "agentdesk-files"
    web_origin: str = "http://localhost:3000"
    session_cookie_name: str = "agentdesk_session"
    csrf_cookie_name: str = "agentdesk_csrf"
    session_ttl_hours: int = 8
    secure_cookies: bool = False
    login_attempt_limit: int = 5
    login_attempt_window_seconds: int = 900
    exchange_rate_api_url: str = "https://open.er-api.com/v6/latest/USD"
    exchange_rate_sync_interval_seconds: int = 21600
    exchange_rate_min_refresh_seconds: int = 86400

    @field_validator("app_secret_key")
    @classmethod
    def reject_default_secret_in_deployed_environments(cls, value: str, info) -> str:
        environment = info.data.get("app_env", "development")
        if environment in {"staging", "production"} and value.startswith("replace-with"):
            raise ValueError("APP_SECRET_KEY must be changed outside development")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
