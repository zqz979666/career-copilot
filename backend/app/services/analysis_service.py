"""Analysis service orchestrating AnalysisAgent + persistence."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.analysis import AnalysisAgent
from app.agents.base import AgentContext
from app.repository.ability_repo import AbilityAssessmentRepository
from app.repository.profile_repo import ProfileRepository
from app.services.event_bus import EventPublisher, StreamEvent
from app.services.profile_engine import ProfileEngine


class AnalysisService:
    def __init__(
        self,
        *,
        analysis_agent: AnalysisAgent,
        profile_engine: ProfileEngine,
        session_factory: async_sessionmaker,
        event_publisher: EventPublisher | None = None,
    ) -> None:
        self._agent = analysis_agent
        self._profile_engine = profile_engine
        self._session_factory = session_factory
        self._event_publisher = event_publisher

    async def assess(self, user_id: UUID, input_content: str = "") -> dict:
        profile_summary = await self._profile_engine.get_summary_text(user_id) or ""
        result = await self._agent.execute(
            AgentContext(
                user_id=str(user_id),
                task_type="ability_assessment",
                input_content=input_content or "请进行最新能力盘点",
                profile_summary=profile_summary,
            )
        )
        payload = result.extracted_data or {}
        dimensions = payload.get("dimensions") if isinstance(payload, dict) else None
        if not isinstance(dimensions, list):
            dimensions = []
        saved_ids: list[str] = []
        async with self._session_factory() as session:
            profile = await ProfileRepository(session).get_or_create(user_id)
            repo = AbilityAssessmentRepository(session)
            for item in dimensions:
                if not isinstance(item, dict):
                    continue
                dimension = str(item.get("dimension") or "").strip()
                if not dimension:
                    continue
                score_raw = item.get("score")
                score = float(score_raw) if isinstance(score_raw, int | float) else None
                prev = await repo.latest_dimension(user_id, dimension)
                trend_delta = round(score - prev.score, 2) if (score is not None and prev and prev.score is not None) else None
                row = await repo.create(
                    user_id=user_id,
                    dimension=dimension,
                    score=score,
                    evidence_chain={
                        "claim": item.get("claim"),
                        "data_ref": item.get("data_ref") if isinstance(item.get("data_ref"), list) else [],
                        "reasoning": item.get("reasoning"),
                        "confidence": item.get("confidence"),
                        "suggestion": item.get("suggestion"),
                    },
                    trend_delta=trend_delta,
                    profile_snapshot_version=profile.version,
                )
                saved_ids.append(str(row.id))
        if self._event_publisher is not None:
            await self._event_publisher.publish(
                StreamEvent(
                    stream="events:task.completed",
                    user_id=str(user_id),
                    payload={"task_type": "ability_assessment", "assessment_ids": saved_ids},
                )
            )
        return {"assessment_ids": saved_ids, "count": len(saved_ids)}

    async def radar(self, user_id: UUID) -> dict:
        async with self._session_factory() as session:
            rows = await AbilityAssessmentRepository(session).latest_by_user(user_id)
        return {
            "dimensions": [
                {
                    "dimension": r.dimension,
                    "score": r.score,
                    "evidence_chain": r.evidence_chain,
                    "assessed_at": r.assessed_at.isoformat(),
                    "trend_delta": r.trend_delta,
                }
                for r in rows
            ]
        }

    async def trend(self, user_id: UUID, dimension: str) -> dict:
        async with self._session_factory() as session:
            rows = await AbilityAssessmentRepository(session).trend(user_id, dimension)
        return {
            "dimension": dimension,
            "points": [
                {"score": r.score, "assessed_at": r.assessed_at.isoformat()}
                for r in rows[::-1]
            ],
        }
