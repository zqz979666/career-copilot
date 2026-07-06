"""ExtractedData repository — feeds the Profile Engine Ingester."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import ExtractedData


class ExtractedDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_uningested(
        self, user_id: UUID, limit: int = 500
    ) -> list[ExtractedData]:
        """Rows not yet folded into profile_entries (``ingested_at IS NULL``)."""
        result = await self.session.execute(
            select(ExtractedData)
            .where(
                ExtractedData.user_id == user_id,
                ExtractedData.ingested_at.is_(None),
                ExtractedData.status != "rejected",
            )
            .order_by(ExtractedData.created_at.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_ingested(self, ids: Sequence[UUID]) -> None:
        if not ids:
            return
        await self.session.execute(
            update(ExtractedData)
            .where(ExtractedData.id.in_(list(ids)))
            .values(ingested_at=datetime.now(UTC))
        )
        await self.session.commit()
