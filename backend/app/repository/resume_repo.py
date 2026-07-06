"""Resume repository — multi-version resume CRUD."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Resume


class ResumeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        title: str,
        content: dict,
        target_jd: str | None = None,
        jd_analysis_id: UUID | None = None,
        token_usage: dict | None = None,
    ) -> Resume:
        resume = Resume(
            user_id=user_id,
            title=title,
            content=content,
            target_jd=target_jd,
            jd_analysis_id=jd_analysis_id,
            token_usage=token_usage,
        )
        self.session.add(resume)
        await self.session.commit()
        await self.session.refresh(resume)
        return resume

    async def list_by_user(self, user_id: UUID) -> list[Resume]:
        result = await self.session.execute(
            select(Resume)
            .where(Resume.user_id == user_id)
            .order_by(Resume.created_at.desc())
        )
        return list(result.scalars().all())

    async def count_by_user(self, user_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count()).select_from(Resume).where(Resume.user_id == user_id)
        )
        return int(result.scalar_one())

    async def get_owned(self, resume_id: UUID, user_id: UUID) -> Resume | None:
        result = await self.session.execute(
            select(Resume).where(Resume.id == resume_id, Resume.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        *,
        resume: Resume,
        title: str | None = None,
        content: dict | None = None,
    ) -> Resume:
        if title is not None:
            resume.title = title
        if content is not None:
            resume.content = content
            resume.version += 1
        await self.session.commit()
        await self.session.refresh(resume)
        return resume

    async def delete(self, resume: Resume) -> None:
        await self.session.delete(resume)
        await self.session.commit()
