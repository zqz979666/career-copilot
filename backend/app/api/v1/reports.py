"""Growth report APIs (v1.0)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import get_current_user_id, get_report_service
from app.services.report_service import ReportService

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.post("/monthly")
async def generate_monthly(
    period: str | None = Query(default=None, max_length=20),
    user_id: UUID = Depends(get_current_user_id),
    svc: ReportService = Depends(get_report_service),
) -> dict:
    return await svc.generate_monthly(user_id, period)


@router.get("/monthly")
async def get_monthly(
    period: str = Query(..., min_length=7, max_length=20),
    user_id: UUID = Depends(get_current_user_id),
    svc: ReportService = Depends(get_report_service),
) -> dict:
    row = await svc.get_monthly(user_id, period)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "report_not_found")
    return row
