"""Trust Ladder service (L1-L3 for v1.0)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.repository.trust_repo import TrustLadderRepository


class TrustService:
    def __init__(self, *, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_level(self, user_id: UUID) -> dict:
        async with self._session_factory() as session:
            row = await TrustLadderRepository(session).get_or_create(user_id)
        return {"level": row.level, "changed_at": row.level_changed_at.isoformat()}

    async def set_level(self, user_id: UUID, level: int) -> dict:
        if level not in {1, 2, 3}:
            raise ValueError("level_must_be_1_2_3")
        async with self._session_factory() as session:
            row = await TrustLadderRepository(session).update_level(user_id, level)
        return {"level": row.level, "changed_at": row.level_changed_at.isoformat()}
