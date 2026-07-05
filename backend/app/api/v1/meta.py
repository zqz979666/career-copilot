"""Meta endpoints (health, version)."""
from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.models.schemas import HealthResponse

router = APIRouter(tags=["meta"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(version=__version__, env=settings.app_env)
