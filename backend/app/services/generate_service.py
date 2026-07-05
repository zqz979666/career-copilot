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

from app.agents.base import AgentContext, AgentRouter
from app.logging_config import get_logger
from app.repository.generation_repo import GenerationRepository
from app.repository.user_repo import UserRepository
from app.services.extraction_service import ExtractionService

logger = get_logger(__name__)


class GenerateService:
    def __init__(
        self,
        router: AgentRouter,
        session_factory: async_sessionmaker,
        extraction: ExtractionService | None = None,
    ) -> None:
        self._router = router
        self._session_factory = session_factory
        self._extraction = extraction

    async def generate_stream(
        self,
        *,
        user_id: UUID | None,
        task_type: str,
        input_content: str,
        input_type: str = "text",
    ) -> AsyncGenerator[str, None]:
        context = AgentContext(
            user_id=str(user_id) if user_id else None,
            task_type=task_type,
            input_content=input_content,
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

        # Fire-and-forget side-effect extraction (`full` mode only).
        if memory_mode == "full" and self._extraction is not None and generation_id is not None:
            asyncio.create_task(
                self._extraction.extract_and_save(
                    user_id=user_id,
                    generation_id=generation_id,
                    task_type=task_type,
                    input_text=input_content,
                    output_text=output_text,
                )
            )

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
