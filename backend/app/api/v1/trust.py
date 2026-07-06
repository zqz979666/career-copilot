"""Trust ladder API (v1.0)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import get_settings
from app.dependencies import get_current_user_id, get_trust_service
from app.models.schemas import TrustLevelRequest
from app.services.trust_service import TrustService

router = APIRouter(prefix="/api/v1/trust", tags=["trust"])


@router.get("/level")
async def get_level(
    user_id: UUID = Depends(get_current_user_id),
    svc: TrustService = Depends(get_trust_service),
) -> dict:
    return await svc.get_level(user_id)


@router.post("/level")
async def set_level(
    body: TrustLevelRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: TrustService = Depends(get_trust_service),
) -> dict:
    settings = get_settings()
    if body.level == 2 and not settings.trust_ladder_l2_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "trust_l2_disabled")
    try:
        return await svc.set_level(user_id, body.level)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
