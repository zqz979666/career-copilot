"""Evidence repository — stores raw source material for the Evidence Chain."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Evidence


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        evidence_type: str,
        raw_content: str | None,
        extracted_facts: dict | None = None,
        generation_id: UUID | None = None,
    ) -> Evidence:
        row = Evidence(
            user_id=user_id,
            evidence_type=evidence_type,
            raw_content=raw_content,
            extracted_facts=extracted_facts or {},
            generation_id=generation_id,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_by_user(self, user_id: UUID, limit: int = 200) -> list[Evidence]:
        result = await self.session.execute(
            select(Evidence)
            .where(Evidence.user_id == user_id)
            .order_by(Evidence.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
