"""Repository for sync_events (v0.8).

The Sync Worker + Webhook handler both funnel here. ``(provider, external_id)``
is UNIQUE, so :meth:`record` is idempotent: repeated webhook deliveries collapse
onto the first row instead of producing duplicate work.
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import SyncEvent


class SyncEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        provider: str,
        event_type: str,
        external_id: str,
        payload: dict,
        user_id: UUID | None = None,
    ) -> tuple[SyncEvent, bool]:
        """Insert a new event (or return the existing one).

        Returns ``(event, created)``. ``created=False`` means the ``(provider,
        external_id)`` tuple was already known — callers should treat this as
        a no-op to keep the pipeline idempotent.
        """
        stmt = (
            pg_insert(SyncEvent)
            .values(
                provider=provider,
                event_type=event_type,
                external_id=external_id,
                payload=payload,
                user_id=user_id,
            )
            .on_conflict_do_nothing(index_elements=["provider", "external_id"])
            .returning(SyncEvent.id)
        )
        result = await self.session.execute(stmt)
        row = result.first()
        if row is None:
            existing = await self.session.execute(
                select(SyncEvent).where(
                    SyncEvent.provider == provider,
                    SyncEvent.external_id == external_id,
                )
            )
            return existing.scalar_one(), False
        await self.session.commit()
        fetched = await self.session.execute(
            select(SyncEvent).where(SyncEvent.id == row[0])
        )
        return fetched.scalar_one(), True

    async def mark_processed(self, event_id: UUID, error: str | None = None) -> None:
        event = await self.session.get(SyncEvent, event_id)
        if event is None:
            return
        event.status = "failed" if error else "processed"
        event.error = error
        event.processed_at = datetime.now(UTC)
        await self.session.commit()

    async def get_by_external_id(
        self, provider: str, external_id: str
    ) -> SyncEvent | None:
        result = await self.session.execute(
            select(SyncEvent).where(
                SyncEvent.provider == provider,
                SyncEvent.external_id == external_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_recent(
        self, user_id: UUID | None = None, *, limit: int = 50
    ) -> list[SyncEvent]:
        stmt = select(SyncEvent).order_by(SyncEvent.created_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(SyncEvent.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
