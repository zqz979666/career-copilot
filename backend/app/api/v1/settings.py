"""User settings endpoints (v0.1).

Currently only exposes ``memory_mode`` — controls whether generations and
extracted side-effects are persisted:

    full       → persist everything (default)
    selective  → persist generations, skip side-effect extraction
    none       → don't persist generations or extracted data at all
                 (client-side effect: history stays empty for this user)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import DbSession, get_current_user_id
from app.models.schemas import SettingsOut, SettingsUpdateRequest
from app.repository.user_repo import UserRepository

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings_endpoint(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> SettingsOut:
    mode = await UserRepository(session).get_memory_mode(user_id)
    if mode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    return SettingsOut(memory_mode=mode)  # type: ignore[arg-type]


@router.patch("", response_model=SettingsOut)
async def update_settings(
    body: SettingsUpdateRequest,
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> SettingsOut:
    user = await UserRepository(session).update_memory_mode(user_id, body.memory_mode)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    return SettingsOut(memory_mode=user.memory_mode)  # type: ignore[arg-type]
