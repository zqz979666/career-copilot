"""Job service orchestrating JobAgent + persistence."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.base import AgentContext
from app.agents.job import JobAgent
from app.repository.job_repo import InterviewDebriefRepository, InterviewKitRepository
from app.services.event_bus import EventPublisher, StreamEvent
from app.services.profile_engine import ProfileEngine
from app.services.profile_merge import Candidate


class JobService:
    def __init__(
        self,
        *,
        job_agent: JobAgent,
        profile_engine: ProfileEngine,
        session_factory: async_sessionmaker,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._agent = job_agent
        self._profile_engine = profile_engine
        self._session_factory = session_factory
        self._event_publisher = event_publisher

    async def create_kit(self, user_id: UUID, jd_text: str = "", jd_analysis_id: UUID | None = None) -> dict:
        profile_summary = await self._profile_engine.get_summary_text(user_id) or ""
        result = await self._agent.execute(
            AgentContext(
                user_id=str(user_id),
                task_type="job_kit",
                input_content=jd_text or "请基于当前用户画像生成面试题",
                profile_summary=profile_summary,
            )
        )
        payload = result.extracted_data or {}
        questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
        pitch = str(payload.get("pitch") or "").strip() or None
        async with self._session_factory() as session:
            row = await InterviewKitRepository(session).create(
                user_id=user_id,
                jd_analysis_id=jd_analysis_id,
                questions=questions,
                pitch=pitch,
            )
        if self._event_publisher is not None:
            await self._event_publisher.publish(
                StreamEvent(
                    stream="events:task.completed",
                    user_id=str(user_id),
                    payload={"task_type": "job_kit", "kit_id": str(row.id)},
                )
            )
        return {"id": str(row.id), "pitch": pitch, "questions": questions}

    async def get_kit(self, user_id: UUID, kit_id: UUID) -> dict | None:
        async with self._session_factory() as session:
            row = await InterviewKitRepository(session).get(kit_id, user_id)
        if row is None:
            return None
        return {
            "id": str(row.id),
            "jd_analysis_id": str(row.jd_analysis_id) if row.jd_analysis_id else None,
            "pitch": row.pitch,
            "questions": row.questions,
            "created_at": row.created_at.isoformat(),
        }

    async def create_debrief(
        self,
        *,
        user_id: UUID,
        notes_md: str,
        company: str | None,
        position: str | None,
        result_text: str | None,
        kit_id: UUID | None,
    ) -> dict:
        async with self._session_factory() as session:
            row = await InterviewDebriefRepository(session).create(
                user_id=user_id,
                kit_id=kit_id,
                company=company,
                position=position,
                result_text=result_text,
                notes_md=notes_md,
            )
        # Debrief is fed back to profile as an achievement candidate.
        candidate = Candidate(
            entry_type="achievement",
            dedup_key=f"debrief:{row.id}",
            content={
                "title": f"{company or '面试'}复盘",
                "description": notes_md[:1000],
                "position": position,
                "result": result_text,
            },
            source_type="user_input",
            source_id=row.id,
            source_ref=f"interview_debrief:{row.id}",
            evidence_ids=[],
        )
        await self._profile_engine.ingest_third_party(user_id, [candidate], recompile=True)
        return {"id": str(row.id)}
