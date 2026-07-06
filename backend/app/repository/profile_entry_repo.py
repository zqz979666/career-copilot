"""ProfileEntry repository — CRUD + dedup lookup + pgvector semantic search."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import ProfileEntry


class ProfileEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        entry_type: str | None = None,
        statuses: tuple[str, ...] | None = None,
        limit: int = 500,
    ) -> list[ProfileEntry]:
        stmt = select(ProfileEntry).where(ProfileEntry.user_id == user_id)
        if entry_type is not None:
            stmt = stmt.where(ProfileEntry.entry_type == entry_type)
        if statuses is not None:
            stmt = stmt.where(ProfileEntry.status.in_(list(statuses)))
        stmt = stmt.order_by(
            ProfileEntry.confidence.desc(), ProfileEntry.updated_at.desc()
        ).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_owned(self, entry_id: UUID, user_id: UUID) -> ProfileEntry | None:
        result = await self.session.execute(
            select(ProfileEntry).where(
                ProfileEntry.id == entry_id, ProfileEntry.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def find_by_dedup(
        self, user_id: UUID, entry_type: str, dedup_key: str
    ) -> ProfileEntry | None:
        result = await self.session.execute(
            select(ProfileEntry).where(
                ProfileEntry.user_id == user_id,
                ProfileEntry.entry_type == entry_type,
                ProfileEntry.dedup_key == dedup_key,
            )
        )
        return result.scalars().first()

    async def find_by_source_ref(
        self, user_id: UUID, source_type: str, source_ref: str
    ) -> ProfileEntry | None:
        """v0.8: look up entry by 3rd-party idempotency key (e.g. github:pr:node)."""
        result = await self.session.execute(
            select(ProfileEntry).where(
                ProfileEntry.user_id == user_id,
                ProfileEntry.source_type == source_type,
                ProfileEntry.source_ref == source_ref,
            )
        )
        return result.scalars().first()

    def add(self, entry: ProfileEntry) -> None:
        self.session.add(entry)

    async def commit(self) -> None:
        await self.session.commit()

    async def count_by_user(self, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(ProfileEntry).where(
                ProfileEntry.user_id == user_id
            )
        )
        return int(result.scalar_one())

    async def semantic_search(
        self,
        user_id: UUID,
        query_embedding: list[float],
        *,
        top_k: int = 40,
        statuses: tuple[str, ...] = ("auto", "confirmed"),
    ) -> list[ProfileEntry]:
        """Return the top-k entries closest to ``query_embedding`` (cosine).

        Entries without an embedding are skipped; callers should fall back to
        :meth:`list_by_user` when this returns fewer than expected.
        """
        distance = ProfileEntry.embedding.cosine_distance(query_embedding)
        stmt = (
            select(ProfileEntry)
            .where(
                ProfileEntry.user_id == user_id,
                ProfileEntry.status.in_(list(statuses)),
                ProfileEntry.embedding.is_not(None),
            )
            .order_by(distance.asc())
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self, entry: ProfileEntry, status: str
    ) -> ProfileEntry:
        entry.status = status
        await self.session.commit()
        await self.session.refresh(entry)
        return entry
