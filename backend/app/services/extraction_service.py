"""Structured side-effect extraction service.

After a generation completes we make a **cheap, best-effort** LLM call to pull
projects / skills / achievements / tech_stack out of the input+output pair.

Design notes (v0.1):
- Runs *after* the SSE response completes so it never blocks user-visible
  latency. Failures are logged and swallowed.
- Uses ``LLMConfig(temperature=0)`` and ``max_tokens=1024`` — keep it small.
- Writes to the `extracted_data` table with ``status='auto'`` and per-item
  ``confidence`` — v0.5 Merger will consume these rows.
- Data is never re-shown to the user in v0.1; this is pure "data heating"
  for later Profile Engine.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.llm.gateway import LLMConfig, LLMGateway
from app.logging_config import get_logger
from app.models.db import ExtractedData

logger = get_logger(__name__)


_SYSTEM_PROMPT = """你是一名信息抽取助手。给定一段用户的工作输入及 AI 生成的整理稿，
请从中抽取以下四类结构化信息，只输出严格的 JSON：

{
  "projects":     [{"name": "...", "role": "...", "summary": "..."}],
  "skills":       ["技能A", "技能B"],
  "achievements": [{"summary": "...", "metric": "可选量化指标"}],
  "tech_stack":   ["技术A", "技术B"]
}

规则：
1. 只抽取用户明确提到的事实，绝不编造
2. 每一类若无内容，返回空数组 []
3. 每条 achievement.summary 不超过 60 字
4. 输出必须是可直接 json.loads 的 JSON，不要包裹 ```json``` 代码围栏
"""


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_fences(text: str) -> str:
    return _JSON_FENCE_RE.sub("", text).strip()


def _extract_json(text: str) -> str:
    text = _strip_fences(text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


class ExtractionService:
    """Extract structured facts from a generation and persist them."""

    def __init__(
        self,
        llm: LLMGateway,
        session_factory: async_sessionmaker,
    ) -> None:
        self._llm = llm
        self._session_factory = session_factory

    async def extract_and_save(
        self,
        *,
        user_id: UUID,
        generation_id: UUID,
        task_type: str,
        input_text: str,
        output_text: str,
    ) -> None:
        """Run extraction; log-and-swallow all failures (fire-and-forget path)."""
        try:
            payload = await self._run_llm(input_text=input_text, output_text=output_text)
        except Exception as e:  # noqa: BLE001
            logger.warning("extraction_llm_failed", error=str(e), generation_id=str(generation_id))
            return

        rows = self._build_rows(user_id=user_id, generation_id=generation_id, payload=payload)
        if not rows:
            return

        try:
            async with self._session_factory() as session:
                session.add_all(rows)
                await session.commit()
            logger.info(
                "extraction_persisted",
                generation_id=str(generation_id),
                task_type=task_type,
                rows=len(rows),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("extraction_persist_failed", error=str(e))

    # ---------- internals ----------

    async def _run_llm(self, *, input_text: str, output_text: str) -> dict[str, Any]:
        user_msg = (
            "【用户原始输入】\n"
            f"{input_text.strip()[:4000]}\n\n"
            "【AI 生成的整理稿】\n"
            f"{output_text.strip()[:4000]}\n"
        )
        raw, _ = await self._llm.generate(
            system_prompt=_SYSTEM_PROMPT,
            user_message=user_msg,
            config=LLMConfig(temperature=0.0, max_tokens=1024),
            cache_system_prompt=True,
        )
        parsed = json.loads(_extract_json(raw))
        if not isinstance(parsed, dict):
            raise ValueError("extraction_root_not_dict")
        return parsed

    @staticmethod
    def _build_rows(
        *,
        user_id: UUID,
        generation_id: UUID,
        payload: dict[str, Any],
    ) -> list[ExtractedData]:
        rows: list[ExtractedData] = []

        for project in _ensure_list(payload.get("projects")):
            if isinstance(project, dict) and (project.get("name") or project.get("summary")):
                rows.append(
                    ExtractedData(
                        user_id=user_id,
                        generation_id=generation_id,
                        data_type="project",
                        data_content=project,
                        confidence=0.6,
                        status="auto",
                    )
                )

        for skill in _ensure_list(payload.get("skills")):
            if isinstance(skill, str) and skill.strip():
                rows.append(
                    ExtractedData(
                        user_id=user_id,
                        generation_id=generation_id,
                        data_type="skill",
                        data_content={"name": skill.strip()},
                        confidence=0.5,
                        status="auto",
                    )
                )

        for achievement in _ensure_list(payload.get("achievements")):
            if isinstance(achievement, dict) and achievement.get("summary"):
                rows.append(
                    ExtractedData(
                        user_id=user_id,
                        generation_id=generation_id,
                        data_type="achievement",
                        data_content=achievement,
                        confidence=0.5,
                        status="auto",
                    )
                )

        for tech in _ensure_list(payload.get("tech_stack")):
            if isinstance(tech, str) and tech.strip():
                rows.append(
                    ExtractedData(
                        user_id=user_id,
                        generation_id=generation_id,
                        data_type="tech_stack",
                        data_content={"name": tech.strip()},
                        confidence=0.6,
                        status="auto",
                    )
                )

        return rows


def _ensure_list(value: Any) -> list:
    return value if isinstance(value, list) else []
