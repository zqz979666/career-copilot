"""Repositories for interview kits/debriefs (v1.0)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import InterviewDebrief, InterviewKit


class InterviewKitRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        jd_analysis_id: UUID | None,
        questions: list,
        pitch: str | None,
    ) -> InterviewKit:
        row = InterviewKit(
            user_id=user_id,
            jd_analysis_id=jd_analysis_id,
            questions=questions,
            pitch=pitch,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def get(self, kit_id: UUID, user_id: UUID) -> InterviewKit | None:
        result = await self.session.execute(
            select(InterviewKit).where(
                InterviewKit.id == kit_id,
                InterviewKit.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


class InterviewDebriefRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        kit_id: UUID | None,
        company: str | None,
        position: str | None,
        result_text: str | None,
        notes_md: str,
    ) -> InterviewDebrief:
        row = InterviewDebrief(
            user_id=user_id,
            kit_id=kit_id,
            company=company,
            position=position,
            result=result_text,
            notes_md=notes_md,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row
