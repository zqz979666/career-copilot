"""Generation repository."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import Generation


class GenerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(
        self,
        *,
        user_id: UUID | None,
        input_text: str,
        input_type: str,
        output_format: str,
        output_text: str,
        generation_time_ms: int | None = None,
        token_usage: dict | None = None,
        extracted_metadata: dict | None = None,
    ) -> Generation:
        gen = Generation(
            user_id=user_id,
            input_text=input_text,
            input_type=input_type,
            output_format=output_format,
            output_text=output_text,
            generation_time_ms=generation_time_ms,
            token_usage=token_usage,
            extracted_metadata=extracted_metadata or {},
        )
        self.session.add(gen)
        await self.session.commit()
        await self.session.refresh(gen)
        return gen

    async def list_by_user(
        self, user_id: UUID, limit: int = 20, offset: int = 0
    ) -> tuple[list[Generation], int]:
        total = (
            await self.session.execute(
                select(func.count()).select_from(Generation).where(Generation.user_id == user_id)
            )
        ).scalar_one()

        items = (
            (
                await self.session.execute(
                    select(Generation)
                    .where(Generation.user_id == user_id)
                    .order_by(Generation.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(items), int(total)

    async def get_owned(self, generation_id: UUID, user_id: UUID) -> Generation | None:
        result = await self.session.execute(
            select(Generation).where(
                Generation.id == generation_id,
                Generation.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def apply_feedback(
        self,
        *,
        generation: Generation,
        user_rating: int | None,
        edited_text: str | None,
    ) -> Generation:
        """Update rating / edited_text on an existing row.

        `edit_ratio` is computed here from :func:`_normalized_edit_ratio` so the
        client only ever sends the raw edited text.
        """
        if user_rating is not None:
            generation.user_rating = user_rating
        if edited_text is not None:
            generation.edited_text = edited_text
            generation.edit_ratio = _normalized_edit_ratio(
                generation.output_text, edited_text
            )
        await self.session.commit()
        await self.session.refresh(generation)
        return generation


def _normalized_edit_ratio(original: str, edited: str) -> float:
    """Return a 0..1 ratio approximating how much the user rewrote the output.

    Uses ``difflib.SequenceMatcher`` — cheap, no dependency, ratio() returns
    a similarity in [0,1] and we invert it to get "how much changed".
    An empty original returns 0.0 to avoid /0; an empty edit returns 1.0.
    """
    from difflib import SequenceMatcher

    if not original:
        return 0.0
    if not edited:
        return 1.0
    ratio = SequenceMatcher(a=original, b=edited, autojunk=False).ratio()
    return round(max(0.0, min(1.0, 1.0 - ratio)), 4)
