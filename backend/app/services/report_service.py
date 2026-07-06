"""Monthly growth report service (v1.0)."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.llm.gateway import LLMConfig, LLMGateway
from app.repository.profile_entry_repo import ProfileEntryRepository
from app.repository.report_repo import GrowthReportRepository


class ReportService:
    def __init__(self, *, llm: LLMGateway, session_factory: async_sessionmaker) -> None:
        self._llm = llm
        self._session_factory = session_factory

    async def generate_monthly(self, user_id: UUID, period: str | None = None) -> dict:
        period = period or datetime.now(UTC).strftime("%Y-%m")
        async with self._session_factory() as session:
            entries = await ProfileEntryRepository(session).list_by_user(
                user_id, statuses=("auto", "confirmed"), limit=100
            )
        metrics = {
            "profile_entries_added": len(entries),
            "top_skills": _top_skills(entries),
            "activity_score": min(len(entries), 100),
        }
        prompt = (
            f"请根据这些指标生成一份职业成长月报（Markdown）：\n"
            f"period={period}\nmetrics={metrics}\n"
            "要求：分为 成果/能力变化/下月计划 三部分。"
        )
        md, _ = await self._llm.generate(
            system_prompt="你是职业成长教练。",
            user_message=prompt,
            config=LLMConfig(temperature=0.3, max_tokens=1400),
            cache_system_prompt=True,
        )
        async with self._session_factory() as session:
            row = await GrowthReportRepository(session).upsert(
                user_id=user_id,
                period=period,
                content_md=md.strip(),
                metrics=metrics,
            )
        return {"id": str(row.id), "period": period, "content_md": row.content_md, "metrics": metrics}

    async def get_monthly(self, user_id: UUID, period: str) -> dict | None:
        async with self._session_factory() as session:
            row = await GrowthReportRepository(session).get(user_id, period)
        if row is None:
            return None
        return {"id": str(row.id), "period": row.period, "content_md": row.content_md, "metrics": row.metrics}


def _top_skills(entries: list) -> list[str]:
    freq: dict[str, int] = {}
    for e in entries:
        if e.entry_type != "skill":
            continue
        name = str((e.content or {}).get("name") or "").strip()
        if not name:
            continue
        freq[name] = freq.get(name, 0) + 1
    return [k for k, _ in sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:5]]
