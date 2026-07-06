"""Profile repository."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Profile


class ProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_user_id(self, user_id: UUID) -> Profile | None:
        result = await self.session.execute(select(Profile).where(Profile.user_id == user_id))
        return result.scalar_one_or_none()

    async def get_or_create(self, user_id: UUID) -> Profile:
        """Return the user's profile row, creating an empty one if missing."""
        profile = await self.get_by_user_id(user_id)
        if profile is not None:
            return profile
        stmt = (
            insert(Profile)
            .values(user_id=user_id, basic_info={}, skills=[], experiences=[])
            .on_conflict_do_nothing(index_elements=[Profile.user_id])
            .returning(Profile)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        row = result.scalar_one_or_none()
        if row is not None:
            return row
        # Lost the race — someone else created it.
        created = await self.get_by_user_id(user_id)
        assert created is not None
        return created

    async def update_snapshot(
        self, *, user_id: UUID, snapshot: dict, summary: str | None
    ) -> Profile:
        """Persist the Profile Engine's compiled snapshot + summary."""
        profile = await self.get_or_create(user_id)
        profile.snapshot = snapshot
        profile.summary = summary
        profile.version += 1
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def upsert_from_resume(
        self,
        *,
        user_id: UUID,
        basic_info: dict,
        skills: list,
        experiences: list,
        raw_resume_url: str | None = None,
    ) -> Profile:
        """Insert or update a profile from a freshly parsed resume.

        v0.1 semantics: replace (last write wins). Fine-grained merging lands
        in v0.5 via the Profile Engine's Merger.
        """
        stmt = (
            insert(Profile)
            .values(
                user_id=user_id,
                basic_info=basic_info,
                skills=skills,
                experiences=experiences,
                raw_resume_url=raw_resume_url,
            )
            .on_conflict_do_update(
                index_elements=[Profile.user_id],
                set_={
                    "basic_info": basic_info,
                    "skills": skills,
                    "experiences": experiences,
                    "raw_resume_url": raw_resume_url,
                    "version": Profile.version + 1,
                },
            )
            .returning(Profile)
        )
        result = await self.session.execute(stmt)
        await self.session.commit()
        return result.scalar_one()
