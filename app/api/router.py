from fastapi import APIRouter

from app.api import borg, content, health, tasks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(tasks.router)
api_router.include_router(content.router)
api_router.include_router(borg.router)
