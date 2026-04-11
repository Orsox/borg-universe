from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings

router = APIRouter(tags=["system"])


@router.get("/health")
async def healthcheck(settings: Settings = Depends(get_settings)) -> dict[str, object]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "supabase_configured": settings.supabase_configured,
        "borg_root": str(settings.borg_root),
        "artifact_root": str(settings.artifact_root),
    }
