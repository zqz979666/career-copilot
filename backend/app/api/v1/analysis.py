"""Analysis APIs (v1.0)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.dependencies import get_analysis_service, get_current_user_id
from app.models.schemas import AnalysisAssessRequest, AnalysisGapRequest
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


@router.post("/assess")
async def assess(
    body: AnalysisAssessRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: AnalysisService = Depends(get_analysis_service),
) -> dict:
    return await svc.assess(user_id, body.input_content)


@router.get("/radar")
async def radar(
    user_id: UUID = Depends(get_current_user_id),
    svc: AnalysisService = Depends(get_analysis_service),
) -> dict:
    return await svc.radar(user_id)


@router.get("/trend")
async def trend(
    dimension: str = Query(..., min_length=1, max_length=80),
    user_id: UUID = Depends(get_current_user_id),
    svc: AnalysisService = Depends(get_analysis_service),
) -> dict:
    return await svc.trend(user_id, dimension)


@router.post("/gap")
async def gap(
    body: AnalysisGapRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: AnalysisService = Depends(get_analysis_service),
) -> dict:
    # v1.0 MVP: gap 基于既有雷达评分返回，不做复杂对标库。
    radar = await svc.radar(user_id)
    return {
        "target_jd_id": str(body.target_jd_id) if body.target_jd_id else None,
        "target_level": body.target_level,
        "gaps": radar.get("dimensions", []),
    }
