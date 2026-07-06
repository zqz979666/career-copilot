"""Repository for ability_assessments (v1.0)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AbilityAssessment


class AbilityAssessmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        dimension: str,
        score: float | None,
        evidence_chain: dict,
        trend_delta: float | None,
        profile_snapshot_version: int,
    ) -> AbilityAssessment:
        row = AbilityAssessment(
            user_id=user_id,
            dimension=dimension,
            score=score,
            evidence_chain=evidence_chain,
            trend_delta=trend_delta,
            profile_snapshot_version=profile_snapshot_version,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def latest_by_user(self, user_id: UUID) -> list[AbilityAssessment]:
        rows = await self.session.execute(
            select(AbilityAssessment)
            .where(AbilityAssessment.user_id == user_id)
            .order_by(AbilityAssessment.dimension.asc(), AbilityAssessment.assessed_at.desc())
        )
        latest: dict[str, AbilityAssessment] = {}
        for row in rows.scalars().all():
            latest.setdefault(row.dimension, row)
        return list(latest.values())

    async def latest_dimension(self, user_id: UUID, dimension: str) -> AbilityAssessment | None:
        result = await self.session.execute(
            select(AbilityAssessment)
            .where(
                AbilityAssessment.user_id == user_id,
                AbilityAssessment.dimension == dimension,
            )
            .order_by(AbilityAssessment.assessed_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def trend(self, user_id: UUID, dimension: str, *, limit: int = 12) -> list[AbilityAssessment]:
        result = await self.session.execute(
            select(AbilityAssessment)
            .where(
                AbilityAssessment.user_id == user_id,
                AbilityAssessment.dimension == dimension,
            )
            .order_by(AbilityAssessment.assessed_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
