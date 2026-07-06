"""Repository for growth_reports."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import GrowthReport


class GrowthReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self, *, user_id: UUID, period: str, content_md: str, metrics: dict
    ) -> GrowthReport:
        result = await self.session.execute(
            select(GrowthReport).where(
                GrowthReport.user_id == user_id,
                GrowthReport.period == period,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = GrowthReport(
                user_id=user_id, period=period, content_md=content_md, metrics=metrics
            )
            self.session.add(row)
        else:
            row.content_md = content_md
            row.metrics = metrics
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get(self, user_id: UUID, period: str) -> GrowthReport | None:
        result = await self.session.execute(
            select(GrowthReport).where(
                GrowthReport.user_id == user_id,
                GrowthReport.period == period,
            )
        )
        return result.scalar_one_or_none()
