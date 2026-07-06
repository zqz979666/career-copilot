"""Job APIs (v1.0)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user_id, get_job_service
from app.models.schemas import JobDebriefRequest, JobKitRequest
from app.services.job_service import JobService

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


@router.post("/kit")
async def create_kit(
    body: JobKitRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: JobService = Depends(get_job_service),
) -> dict:
    return await svc.create_kit(user_id, jd_text=body.jd_text or "", jd_analysis_id=body.jd_analysis_id)


@router.get("/kit/{kit_id}")
async def get_kit(
    kit_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    svc: JobService = Depends(get_job_service),
) -> dict:
    row = await svc.get_kit(user_id, kit_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "kit_not_found")
    return row


@router.post("/debrief")
async def create_debrief(
    body: JobDebriefRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: JobService = Depends(get_job_service),
) -> dict:
    return await svc.create_debrief(
        user_id=user_id,
        notes_md=body.notes_md,
        company=body.company,
        position=body.position,
        result_text=body.result,
        kit_id=body.kit_id,
    )
