from __future__ import annotations

from fastapi import APIRouter

from agentdesk_api.api.auth import AppSettings, SuperAdminDependency

router = APIRouter(prefix="/system", tags=["settings"])


@router.get("/openrouter/status")
async def openrouter_status(
    _: SuperAdminDependency,
    settings: AppSettings,
) -> dict[str, object]:
    return {
        "data": {
            "configured": bool(settings.openrouter_api_key),
            "base_url": settings.openrouter_base_url,
            "app_title": settings.openrouter_app_title,
            "secret_source": "OPENROUTER_API_KEY",
        }
    }
