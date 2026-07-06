"""JD analysis endpoints — deep analysis + match assessment (Evidence Chain).

Level 0 (anonymous) callers get the analysis report only. Logged-in callers
additionally get a match assessment against their Profile.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.middleware.rate_limit import enforce_generate_rate_limit
from app.dependencies import (
    DbSession,
    get_current_user_id,
    get_jd_service,
    get_optional_user_id,
)
from app.logging_config import get_logger
from app.models.schemas import JDAnalysisOut, JDAnalyzeRequest
from app.repository.jd_repo import JDAnalysisRepository
from app.services.jd_service import JDService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/jd", tags=["jd"])


@router.post(
    "/analyze",
    response_model=JDAnalysisOut,
    dependencies=[Depends(enforce_generate_rate_limit)],
)
async def analyze_jd(
    body: JDAnalyzeRequest,
    user_id: UUID | None = Depends(get_optional_user_id),
    svc: JDService = Depends(get_jd_service),
) -> JDAnalysisOut:
    result = await svc.analyze(
        user_id=user_id, jd_text=body.jd_text, with_matching=body.with_matching
    )
    return JDAnalysisOut(
        id=result.id,
        analysis=result.analysis,
        matching=result.matching,
        overall_score=result.overall_score,
    )


@router.get("/analyses", response_model=list[JDAnalysisOut])
async def list_analyses(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> list[JDAnalysisOut]:
    rows = await JDAnalysisRepository(session).list_by_user(user_id)
    return [
        JDAnalysisOut(
            id=r.id, analysis=r.analysis, matching=r.matching, overall_score=r.overall_score
        )
        for r in rows
    ]


@router.get("/analyses/{jd_id}", response_model=JDAnalysisOut)
async def get_analysis(
    jd_id: UUID,
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> JDAnalysisOut:
    row = await JDAnalysisRepository(session).get_owned(jd_id, user_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "jd_analysis_not_found")
    return JDAnalysisOut(
        id=row.id, analysis=row.analysis, matching=row.matching, overall_score=row.overall_score
    )
