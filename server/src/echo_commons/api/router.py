"""Top-level API router."""

from fastapi import APIRouter

from echo_server.api.routes.health import router as health_router
from echo_server.api.routes.messages import router as messages_router
from echo_server.api.routes.reflection import router as reflection_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(messages_router)
api_router.include_router(reflection_router)
