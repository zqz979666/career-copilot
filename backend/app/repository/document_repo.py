"""Repository for document_blobs."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import DocumentBlob


class DocumentBlobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: UUID,
        filename: str,
        content_type: str | None,
        content: bytes,
        extracted_summary: str | None,
    ) -> DocumentBlob:
        row = DocumentBlob(
            user_id=user_id,
            filename=filename,
            content_type=content_type,
            content=content,
            extracted_summary=extracted_summary,
        )
        self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def list_recent(self, user_id: UUID, *, limit: int = 20) -> list[DocumentBlob]:
        result = await self.session.execute(
            select(DocumentBlob)
            .where(DocumentBlob.user_id == user_id)
            .order_by(DocumentBlob.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
