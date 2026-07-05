"""History endpoints — list past generations + submit feedback."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import DbSession, get_current_user_id
from app.models.schemas import (
    GenerationFeedbackRequest,
    GenerationOut,
    HistoryList,
)
from app.repository.generation_repo import GenerationRepository

router = APIRouter(prefix="/api/v1", tags=["history"])


@router.get("/history", response_model=HistoryList)
async def list_history(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> HistoryList:
    repo = GenerationRepository(session)
    rows, total = await repo.list_by_user(user_id, limit=limit, offset=offset)
    return HistoryList(
        items=[GenerationOut.model_validate(r) for r in rows],
        total=total,
    )


@router.patch("/history/{generation_id}", response_model=GenerationOut)
async def submit_feedback(
    generation_id: UUID,
    body: GenerationFeedbackRequest,
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> GenerationOut:
    """Attach user feedback to a past generation.

    Both ``user_rating`` (1-5) and ``edited_text`` are optional; at least one
    must be present. ``edit_ratio`` is computed server-side from
    ``edited_text`` vs the stored ``output_text``.
    """
    if body.user_rating is None and body.edited_text is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty_feedback")

    repo = GenerationRepository(session)
    generation = await repo.get_owned(generation_id, user_id)
    if generation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "generation_not_found")

    updated = await repo.apply_feedback(
        generation=generation,
        user_rating=body.user_rating,
        edited_text=body.edited_text,
    )
    return GenerationOut.model_validate(updated)
