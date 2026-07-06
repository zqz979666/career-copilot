"""JDService — JD deep analysis + match assessment (Evidence Chain).

Orchestrates the ResumeAgent (LLM) + ProfileEngine (data) + persistence.
Level 0 (anonymous) callers get the analysis only; matching requires a profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.resume import ResumeAgent
from app.logging_config import get_logger
from app.repository.jd_repo import JDAnalysisRepository
from app.services import evidence as ev
from app.services.profile_engine import ProfileEngine

logger = get_logger(__name__)


@dataclass
class JDResult:
    id: UUID | None
    analysis: dict[str, Any]
    matching: dict[str, Any]
    overall_score: float | None
    token_usage: dict | None


class JDService:
    def __init__(
        self,
        *,
        resume_agent: ResumeAgent,
        profile_engine: ProfileEngine,
        session_factory: async_sessionmaker,
    ) -> None:
        self._agent = resume_agent
        self._engine = profile_engine
        self._session_factory = session_factory

    async def analyze(
        self,
        *,
        user_id: UUID | None,
        jd_text: str,
        with_matching: bool = True,
    ) -> JDResult:
        analysis_res = await self._agent.analyze_jd(jd_text=jd_text)
        analysis = analysis_res.data
        cost = analysis_res.usage.cost_usd

        matching: dict[str, Any] = {}
        overall: float | None = None

        if user_id is not None and with_matching:
            profile_block = await self._profile_block(user_id, jd_text)
            requirements = self._requirements_block(analysis)
            if profile_block and requirements:
                match_res = await self._agent.match_assessment(
                    profile_block=profile_block, requirements_block=requirements
                )
                cost += match_res.usage.cost_usd
                items = ev.build_chain(match_res.data.get("items"))
                overall = ev.overall_score(items)
                matching = {
                    "items": [i.to_dict() for i in items],
                    "gap_counts": ev.summarize_gaps(items),
                    "overall_score": overall,
                }
            else:
                matching = {
                    "items": [],
                    "gap_counts": {},
                    "overall_score": None,
                    "note": "暂无足够的画像数据进行匹配，请先录入工作成果或上传简历。",
                }

        usage = {"cost_usd": round(cost, 6)}

        jd_id: UUID | None = None
        if user_id is not None:
            async with self._session_factory() as session:
                row = await JDAnalysisRepository(session).create(
                    user_id=user_id,
                    jd_text=jd_text,
                    analysis=analysis,
                    matching=matching,
                    overall_score=overall,
                    token_usage=usage,
                )
                jd_id = row.id

        logger.info(
            "jd_analyzed",
            user_id=str(user_id) if user_id else None,
            matched=bool(matching.get("items")),
            overall=overall,
        )
        return JDResult(
            id=jd_id, analysis=analysis, matching=matching, overall_score=overall, token_usage=usage
        )

    # ---------- helpers ----------

    async def _profile_block(self, user_id: UUID, jd_text: str) -> str:
        summary = await self._engine.get_summary_text(user_id)
        entries = await self._engine.retrieve(user_id, jd_text, top_k=40)
        return build_profile_block(summary, entries)

    @staticmethod
    def _requirements_block(analysis: dict[str, Any]) -> str:
        lines: list[str] = []
        for req in analysis.get("core_requirements") or []:
            if str(req).strip():
                lines.append(f"- [核心] {str(req).strip()}")
        for req in analysis.get("implicit_requirements") or []:
            if str(req).strip():
                lines.append(f"- [隐含] {str(req).strip()}")
        return "\n".join(lines)


def build_profile_block(summary: str | None, entries: list) -> str:
    """Compose a text profile block from the compiled summary + top entries.

    Shared by JD matching and resume generation so both see the same context.
    """
    parts: list[str] = []
    if summary:
        parts.append(summary.strip())

    skills: list[str] = []
    projects: list[str] = []
    achievements: list[str] = []
    for e in entries:
        content = getattr(e, "content", {}) or {}
        etype = getattr(e, "entry_type", "")
        if etype in ("skill", "tech"):
            name = content.get("name")
            if name:
                skills.append(str(name))
        elif etype == "project":
            name = content.get("name") or ""
            summ = content.get("summary") or ""
            projects.append(f"{name}：{summ}".strip("："))
        elif etype == "achievement":
            summ = content.get("summary") or ""
            metric = content.get("metric")
            achievements.append(summ + (f"（{metric}）" if metric else ""))

    skills = list(dict.fromkeys(skills))
    if skills:
        parts.append("相关技能：" + "、".join(skills[:30]))
    if projects:
        parts.append("相关项目：\n" + "\n".join(f"  - {p}" for p in projects[:15]))
    if achievements:
        parts.append("相关成果：\n" + "\n".join(f"  - {a}" for a in achievements[:15]))

    return "\n".join(parts).strip()
