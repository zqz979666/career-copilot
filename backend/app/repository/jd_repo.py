"""JDAnalysis repository."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import JDAnalysis


class JDAnalysisRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID | None,
        jd_text: str,
        analysis: dict,
        matching: dict | None = None,
        overall_score: float | None = None,
        token_usage: dict | None = None,
    ) -> JDAnalysis:
        row = JDAnalysis(
            user_id=user_id,
            jd_text=jd_text,
            analysis=analysis,
            matching=matching or {},
            overall_score=overall_score,
            token_usage=token_usage,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get_owned(self, jd_id: UUID, user_id: UUID) -> JDAnalysis | None:
        result = await self.session.execute(
            select(JDAnalysis).where(
                JDAnalysis.id == jd_id, JDAnalysis.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: UUID, limit: int = 50) -> list[JDAnalysis]:
        result = await self.session.execute(
            select(JDAnalysis)
            .where(JDAnalysis.user_id == user_id)
            .order_by(JDAnalysis.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
