"""Document upload + extraction + profile ingest (v1.0)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.prompt_loader import load_prompt
from app.document.parser import DocumentParseError, extract_resume_text
from app.llm.gateway import LLMConfig, LLMGateway
from app.repository.document_repo import DocumentBlobRepository
from app.services.profile_engine import ProfileEngine
from app.services.profile_merge import Candidate


class DocumentService:
    def __init__(
        self,
        *,
        llm: LLMGateway,
        profile_engine: ProfileEngine,
        session_factory: async_sessionmaker,
    ) -> None:
        self._llm = llm
        self._profile_engine = profile_engine
        self._session_factory = session_factory

    async def upload(
        self,
        *,
        user_id: UUID,
        filename: str | None,
        content_type: str | None,
        data: bytes,
    ) -> dict:
        try:
            parsed = extract_resume_text(
                data=data,
                filename=filename,
                content_type=content_type,
            )
        except DocumentParseError as e:
            raise ValueError(str(e)) from e

        # Reuse existing extraction prompt as fallback to keep v1.0 lean.
        prompt = load_prompt("free_format")
        raw, _ = await self._llm.generate(
            system_prompt=prompt.system,
            user_message=prompt.render(input_content=parsed.text[:8000]),
            config=LLMConfig(temperature=0.2, max_tokens=1200),
            cache_system_prompt=True,
        )
        summary = raw.strip()[:4000]
        blob_id = None
        async with self._session_factory() as session:
            blob = await DocumentBlobRepository(session).create(
                user_id=user_id,
                filename=filename or "document",
                content_type=content_type,
                content=data,
                extracted_summary=summary,
            )
            blob_id = str(blob.id)

        candidates = [
            Candidate(
                entry_type="achievement",
                dedup_key=f"document:{blob_id}",
                content={"title": filename or "导入文档", "description": summary[:1000]},
                source_type="user_input",
                source_id=None,
                source_ref=f"document:{blob_id}",
                evidence_ids=[],
            )
        ]
        await self._profile_engine.ingest_third_party(user_id, candidates, recompile=True)
        return {
            "document_id": blob_id,
            "source_format": parsed.format,
            "source_page_count": parsed.page_count,
            "source_chars": len(parsed.text),
            "summary": summary,
        }
