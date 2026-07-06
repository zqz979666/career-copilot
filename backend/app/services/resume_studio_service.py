"""ResumeStudioService — orchestrates resume generation / management / export.

Data flows through the ProfileEngine (retrieval) → ResumeAgent (LLM) →
ResumeRepository (persistence). JD-tailored generation additionally runs the
JDService to obtain a match assessment that biases the resume content.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.resume import ResumeAgent
from app.config import get_settings
from app.logging_config import get_logger
from app.models.db import Resume
from app.repository.resume_repo import ResumeRepository
from app.services.jd_service import JDService, build_profile_block
from app.services.profile_engine import ProfileEngine

logger = get_logger(__name__)


class ResumeStudioError(Exception):
    """Base error for the resume studio."""


class NoProfileDataError(ResumeStudioError):
    """Raised when there is not enough profile data to generate a resume."""


class ResumeLimitError(ResumeStudioError):
    """Raised when the per-user resume version cap is reached."""


class ResumeStudioService:
    def __init__(
        self,
        *,
        resume_agent: ResumeAgent,
        profile_engine: ProfileEngine,
        jd_service: JDService,
        session_factory: async_sessionmaker,
    ) -> None:
        self._agent = resume_agent
        self._engine = profile_engine
        self._jd = jd_service
        self._session_factory = session_factory
        self._settings = get_settings()

    # ---------- generation ----------

    async def generate(
        self, *, user_id: UUID, title: str, jd_text: str | None = None
    ) -> Resume:
        # 1. Assemble profile context (semantic retrieval when a JD is present).
        summary = await self._engine.get_summary_text(user_id)
        entries = await self._engine.retrieve(
            user_id, jd_text, top_k=self._settings.resume_retrieval_top_k
        )
        profile_block = build_profile_block(summary, entries)
        if not profile_block:
            raise NoProfileDataError(
                "no_profile_data: 请先录入工作成果或上传简历以建立画像。"
            )

        # 2. Optional JD tailoring → match assessment.
        jd_block = ""
        match_block = ""
        jd_analysis_id: UUID | None = None
        if jd_text:
            jd_result = await self._jd.analyze(
                user_id=user_id, jd_text=jd_text, with_matching=True
            )
            jd_analysis_id = jd_result.id
            jd_block = jd_text
            match_block = _match_block_text(jd_result.matching)

        # 3. Generate the resume content.
        result = await self._agent.generate_resume(
            profile_block=profile_block, jd_block=jd_block, match_block=match_block
        )
        content = result.data

        # 4. Persist (enforce version cap).
        async with self._session_factory() as session:
            repo = ResumeRepository(session)
            count = await repo.count_by_user(user_id)
            if count >= self._settings.resume_max_versions:
                raise ResumeLimitError(
                    f"resume_limit_reached: 最多保存 {self._settings.resume_max_versions} 份简历"
                )
            resume = await repo.create(
                user_id=user_id,
                title=title,
                content=content,
                target_jd=jd_text,
                jd_analysis_id=jd_analysis_id,
                token_usage=result.usage.to_dict(),
            )
        logger.info(
            "resume_generated",
            user_id=str(user_id),
            resume_id=str(resume.id),
            tailored=bool(jd_text),
        )
        return resume

    async def diagnose(self, *, resume_text: str) -> dict[str, Any]:
        result = await self._agent.diagnose_resume(resume_text=resume_text)
        return result.data

    # ---------- management ----------

    async def list(self, user_id: UUID) -> list[Resume]:
        async with self._session_factory() as session:
            return await ResumeRepository(session).list_by_user(user_id)

    async def get(self, user_id: UUID, resume_id: UUID) -> Resume | None:
        async with self._session_factory() as session:
            return await ResumeRepository(session).get_owned(resume_id, user_id)

    async def update(
        self,
        *,
        user_id: UUID,
        resume_id: UUID,
        title: str | None = None,
        content: dict | None = None,
    ) -> Resume | None:
        async with self._session_factory() as session:
            repo = ResumeRepository(session)
            resume = await repo.get_owned(resume_id, user_id)
            if resume is None:
                return None
            return await repo.update(resume=resume, title=title, content=content)

    async def delete(self, user_id: UUID, resume_id: UUID) -> bool:
        async with self._session_factory() as session:
            repo = ResumeRepository(session)
            resume = await repo.get_owned(resume_id, user_id)
            if resume is None:
                return False
            await repo.delete(resume)
            return True


def _match_block_text(matching: dict[str, Any]) -> str:
    """Condense a match assessment into guidance for the resume generator."""
    items = matching.get("items") or []
    if not items:
        return ""
    lines: list[str] = []
    score = matching.get("overall_score")
    if score is not None:
        lines.append(f"整体匹配度：{score}/100")
    for it in items:
        status = it.get("status")
        req = it.get("requirement")
        sug = it.get("suggestion")
        lines.append(f"- [{status}] {req}" + (f" → 建议：{sug}" if sug else ""))
    return "\n".join(lines)
