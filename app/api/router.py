from fastapi import APIRouter

from app.api import borg, content, health, orchestration, tasks, workflows

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tasks.router)
api_router.include_router(workflows.router)
api_router.include_router(content.router)
api_router.include_router(borg.router)
api_router.include_router(orchestration.router)
