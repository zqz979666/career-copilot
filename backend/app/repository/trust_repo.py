"""Repository for trust_ladder_state."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import TrustLadderState


class TrustLadderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(self, user_id: UUID) -> TrustLadderState:
        result = await self.session.execute(
            select(TrustLadderState).where(TrustLadderState.user_id == user_id)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        row = TrustLadderState(user_id=user_id, level=1)
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def update_level(self, user_id: UUID, level: int) -> TrustLadderState:
        row = await self.get_or_create(user_id)
        row.level = level
        row.level_changed_at = datetime.now(UTC)
        await self.session.commit()
        await self.session.refresh(row)
        return row
