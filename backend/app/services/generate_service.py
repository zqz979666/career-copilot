"""GenerateService — bridges the API layer and the Agent layer.

Responsibilities in v0.1:
    - Route the request via :class:`AgentRouter`.
    - Stream chunks back to the caller (SSE endpoint).
    - Persist a `generations` row after the stream finishes (best-effort).
    - Honor the user's ``memory_mode`` (full / selective / none):
        * ``none``       → never persist, never extract side-effects
        * ``selective``  → persist generation, skip side-effect extraction
        * ``full``       → persist + extract (default)

Anonymous (Level 0) users skip persistence entirely regardless of mode.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.base import AgentContext
from app.agents.master import MasterAgent
from app.logging_config import get_logger
from app.repository.generation_repo import GenerationRepository
from app.repository.user_repo import UserRepository
from app.services.extraction_service import ExtractionService
from app.services.profile_engine import ProfileEngine

logger = get_logger(__name__)


class GenerateService:
    def __init__(
        self,
        router: MasterAgent,
        session_factory: async_sessionmaker,
        extraction: ExtractionService | None = None,
        profile_engine: ProfileEngine | None = None,
    ) -> None:
        self._router = router
        self._session_factory = session_factory
        self._extraction = extraction
        self._profile_engine = profile_engine

    async def classify_intent(self, input_content: str):
        """Return the Master Agent's full IntentResult for ``input_content``."""
        return await self._router.classify(input_content)

    async def resolve_intent(self, input_content: str) -> str:
        """Resolve a concrete task_type for the "auto" entry point."""
        result = await self._router.classify(input_content)
        logger.info(
            "intent_resolved",
            intent=result.intent,
            task_type=result.task_type,
            method=result.method,
        )
        return result.task_type

    async def generate_stream(
        self,
        *,
        user_id: UUID | None,
        task_type: str,
        input_content: str,
        input_type: str = "text",
    ) -> AsyncGenerator[str, None]:
        # "auto" → Master Agent intent classification (rule → Haiku fallback).
        if task_type == "auto":
            task_type = await self.resolve_intent(input_content)

        # Load profile summary for logged-in users (skipped in memory none path
        # is handled after generation; injecting context is safe and cheap).
        profile_summary = None
        if user_id is not None and self._profile_engine is not None:
            try:
                profile_summary = await self._profile_engine.get_summary_text(user_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("profile_summary_load_failed", error=str(e))

        # Monthly report aggregates recent generations into the input context.
        agent_input = input_content
        if task_type == "monthly_report" and user_id is not None:
            agent_input = await self._augment_monthly(user_id, input_content)

        context = AgentContext(
            user_id=str(user_id) if user_id else None,
            task_type=task_type,
            input_content=agent_input,
            profile_summary=profile_summary,
        )
        agent = self._router.route(context)

        started = time.time()
        chunks: list[str] = []

        async for chunk in agent.stream(context):
            chunks.append(chunk)
            yield chunk

        elapsed_ms = int((time.time() - started) * 1000)
        output_text = "".join(chunks)

        if user_id is None or not output_text:
            # Anonymous / empty output → nothing to persist.
            return

        # Look up memory_mode; treat unknown user as "full" so we don't silently drop data.
        memory_mode = await self._load_memory_mode(user_id) or "full"
        if memory_mode == "none":
            logger.info("generation_skipped_memory_none", user_id=str(user_id))
            return

        try:
            generation_id = await self._save_generation(
                user_id=user_id,
                input_text=input_content,
                input_type=input_type,
                output_format=task_type,
                output_text=output_text,
                generation_time_ms=elapsed_ms,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("generation_persist_failed", error=str(e))
            return

        # Fire-and-forget: extract structured facts → ingest into Profile Engine.
        if memory_mode == "full" and self._extraction is not None and generation_id is not None:
            asyncio.create_task(
                self._extract_then_ingest(
                    user_id=user_id,
                    generation_id=generation_id,
                    task_type=task_type,
                    input_text=input_content,
                    output_text=output_text,
                )
            )

    async def _extract_then_ingest(
        self,
        *,
        user_id: UUID,
        generation_id: UUID,
        task_type: str,
        input_text: str,
        output_text: str,
    ) -> None:
        """Run side-effect extraction, then fold new facts into the profile.

        Both steps swallow their own errors; this wrapper guards the seam so a
        failure in extraction never leaves the Profile Engine half-run.
        """
        try:
            await self._extraction.extract_and_save(  # type: ignore[union-attr]
                user_id=user_id,
                generation_id=generation_id,
                task_type=task_type,
                input_text=input_text,
                output_text=output_text,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("extraction_stage_failed", error=str(e))
            return
        if self._profile_engine is not None:
            try:
                await self._profile_engine.ingest_and_recompile(user_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("profile_ingest_stage_failed", error=str(e))

    async def _augment_monthly(self, user_id: UUID, input_content: str) -> str:
        """Prepend recent weekly/free generations so the monthly rollup has data."""
        try:
            async with self._session_factory() as session:
                repo = GenerationRepository(session)
                rows, _ = await repo.list_by_user(user_id, limit=12, offset=0)
        except Exception as e:  # noqa: BLE001
            logger.warning("monthly_history_load_failed", error=str(e))
            return input_content

        history = [
            r.output_text
            for r in rows
            if r.output_format in ("weekly_report", "free_format", "pr_parse", "meeting_parse")
        ]
        if not history:
            return input_content
        block = "\n\n---\n\n".join(history[:8])
        extra = f"\n\n【本月补充说明】\n{input_content.strip()}" if input_content.strip() else ""
        return f"【近期已生成的工作记录】\n{block}{extra}"

    async def _load_memory_mode(self, user_id: UUID) -> str | None:
        try:
            async with self._session_factory() as session:
                return await UserRepository(session).get_memory_mode(user_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("memory_mode_lookup_failed", error=str(e))
            return None

    async def _save_generation(
        self,
        *,
        user_id: UUID,
        input_text: str,
        input_type: str,
        output_format: str,
        output_text: str,
        generation_time_ms: int,
    ) -> UUID | None:
        async with self._session_factory() as session:
            repo = GenerationRepository(session)
            row = await repo.save(
                user_id=user_id,
                input_text=input_text,
                input_type=input_type,
                output_format=output_format,
                output_text=output_text,
                generation_time_ms=generation_time_ms,
            )
            return row.id
