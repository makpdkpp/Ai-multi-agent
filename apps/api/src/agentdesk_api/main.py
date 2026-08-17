from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agentdesk_api import __version__
from agentdesk_api.api.agents import router as agents_router
from agentdesk_api.api.auth import me_router
from agentdesk_api.api.auth import router as auth_router
from agentdesk_api.api.chat import router as chat_router
from agentdesk_api.api.data_sources import router as data_sources_router
from agentdesk_api.api.departments import router as departments_router
from agentdesk_api.api.handoff import router as handoff_router
from agentdesk_api.api.health import router as health_router
from agentdesk_api.api.llm_profiles import router as llm_profiles_router
from agentdesk_api.api.router import router as api_router
from agentdesk_api.api.settings import router as settings_router
from agentdesk_api.api.usage import refresh_exchange_rate_if_stale
from agentdesk_api.api.usage import router as usage_router
from agentdesk_api.api.widget import router as widget_router
from agentdesk_api.config import get_settings
from agentdesk_api.db.session import async_session_factory, engine

settings = get_settings()
logger = logging.getLogger(__name__)


async def exchange_rate_scheduler() -> None:
    while True:
        try:
            async with async_session_factory() as session:
                await refresh_exchange_rate_if_stale(session, settings)
                await session.commit()
        except Exception:
            logger.exception("exchange_rate_refresh_failed")
        await asyncio.sleep(settings.exchange_rate_sync_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    exchange_task = asyncio.create_task(exchange_rate_scheduler())
    try:
        yield
    finally:
        exchange_task.cancel()
        with suppress(asyncio.CancelledError):
            await exchange_task
        await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key", "If-Match"],
)
app.include_router(health_router)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(me_router, prefix=settings.api_v1_prefix)
app.include_router(departments_router, prefix=settings.api_v1_prefix)
app.include_router(agents_router, prefix=settings.api_v1_prefix)
app.include_router(chat_router, prefix=settings.api_v1_prefix)
app.include_router(data_sources_router, prefix=settings.api_v1_prefix)
app.include_router(settings_router, prefix=settings.api_v1_prefix)
app.include_router(usage_router, prefix=settings.api_v1_prefix)
app.include_router(llm_profiles_router, prefix=settings.api_v1_prefix)
app.include_router(handoff_router, prefix=settings.api_v1_prefix)
app.include_router(widget_router, prefix=settings.api_v1_prefix)
app.include_router(api_router, prefix=settings.api_v1_prefix)
