"""Integrations meta endpoints (v0.8).

Cheap read endpoints for the Integrations page:

    GET /api/v1/integrations/events?limit=50

The OAuth flow itself lives in :mod:`app.api.v1.oauth`; the webhook receiver
lives in :mod:`app.api.v1.webhooks`. This module only surfaces sync ledger
data so the UI can render "n events in the last 24h, m succeeded".
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.dependencies import DbSession, get_current_user_id
from app.models.schemas import SyncEventList, SyncEventOut
from app.repository.sync_event_repo import SyncEventRepository

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("/events", response_model=SyncEventList)
async def list_events(
    session: DbSession,
    limit: int = 50,
    user_id: UUID = Depends(get_current_user_id),
) -> SyncEventList:
    limit = max(1, min(limit, 200))
    rows = await SyncEventRepository(session).list_recent(user_id, limit=limit)
    return SyncEventList(
        items=[SyncEventOut.model_validate(r) for r in rows], total=len(rows)
    )
