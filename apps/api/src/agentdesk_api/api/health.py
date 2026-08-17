from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from agentdesk_api.config import get_settings
from agentdesk_api.db.session import async_session_factory

router = APIRouter(tags=["operations"])


@router.get("/health", summary="Process liveness")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _check_postgres() -> None:
    async with async_session_factory() as session:
        await session.execute(text("SELECT 1"))


async def _check_redis() -> None:
    settings = get_settings()
    client = Redis.from_url(settings.redis_url, socket_connect_timeout=2)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _check_minio() -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=2) as client:
        response = await client.get(f"{settings.s3_endpoint_url}/minio/health/live")
        response.raise_for_status()


@router.get("/ready", summary="Dependency readiness")
async def readiness(response: Response) -> dict[str, object]:
    checks = {"postgres": _check_postgres(), "redis": _check_redis(), "minio": _check_minio()}
    results = await asyncio.gather(*checks.values(), return_exceptions=True)
    states = {
        name: "ok" if not isinstance(result, BaseException) else "unavailable"
        for name, result in zip(checks, results, strict=True)
    }
    ready = all(value == "ok" for value in states.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else "not_ready", "checks": states}
