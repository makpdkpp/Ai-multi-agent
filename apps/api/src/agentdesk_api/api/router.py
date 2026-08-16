from fastapi import APIRouter

router = APIRouter()


@router.get("/system/info", tags=["system"])
async def system_info() -> dict[str, str]:
    return {"name": "AgentDesk API", "phase": "foundation", "version": "0.1.0"}

