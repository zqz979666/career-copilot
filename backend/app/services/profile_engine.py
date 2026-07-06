"""Profile Engine v0.5 — the single read/write channel for user profile data.

Pipeline (per architecture red-line: PE is the only door to profile data):

    extracted_data / resume  →  Ingester  →  Merger (entity alignment)
                                                 │
                              ConfidenceScorer ──┤
                                                 ▼
                                         profile_entries  ── embeddings (pgvector)
                                                 │
                                          Summarizer
                                                 ▼
                                    profiles.snapshot + profiles.summary

v0.8 adds a 3rd-party ingest path: :meth:`ingest_third_party` takes candidates
sourced from GitHub (webhook or manual pull), routes them through the same
Merger + ConfidenceScorer, and uses ``source_ref`` for idempotent upserts.

Retrieval (:meth:`retrieve`) powers JD-matching and resume generation by
returning the most relevant entries for a query (semantic when embeddings are
available, else confidence/recency ordering).
"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.llm.embeddings import EmbeddingService
from app.logging_config import get_logger
from app.models.db import ProfileEntry
from app.repository.extracted_data_repo import ExtractedDataRepository
from app.repository.profile_entry_repo import ProfileEntryRepository
from app.repository.profile_repo import ProfileRepository
from app.services import profile_merge as pm

logger = get_logger(__name__)


class ProfileEngine:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        embeddings: EmbeddingService,
    ) -> None:
        self._session_factory = session_factory
        self._embeddings = embeddings

    # ---------- public API ----------

    async def ingest_and_recompile(self, user_id: UUID) -> dict:
        """Fold pending extracted_data into profile_entries, then recompile.

        Returns a small stats dict (rows ingested / entries touched).
        """
        stats = await self._ingest(user_id)
        await self.recompile_snapshot(user_id)
        logger.info("profile_engine_ingest_done", user_id=str(user_id), **stats)
        return stats

    async def seed_from_resume(self, user_id: UUID, parsed: dict) -> dict:
        """Create high-confidence entries from a parsed resume, then recompile."""
        candidates = pm.resume_to_candidates(parsed)
        touched = await self._merge_candidates(user_id, candidates)
        await self.recompile_snapshot(user_id)
        logger.info(
            "profile_engine_resume_seed",
            user_id=str(user_id),
            candidates=len(candidates),
            **touched,
        )
        return touched

    async def ingest_third_party(
        self,
        user_id: UUID,
        candidates: list[pm.Candidate],
        *,
        recompile: bool = True,
    ) -> dict:
        """Merge candidates from a 3rd-party source (v0.8: GitHub) and recompile.

        Uses ``source_ref`` for idempotent upserts, so repeated webhook
        deliveries of the same PR update the existing row instead of creating
        duplicates. Falls back to ``dedup_key`` when ``source_ref`` is unset.
        """
        if not candidates:
            return {"created": 0, "updated": 0}
        touched = await self._merge_candidates(user_id, candidates)
        if recompile:
            await self.recompile_snapshot(user_id)
        logger.info(
            "profile_engine_third_party_ingest",
            user_id=str(user_id),
            candidates=len(candidates),
            **touched,
        )
        return touched

    async def retrieve(
        self, user_id: UUID, query: str | None, *, top_k: int = 40
    ) -> list[ProfileEntry]:
        """Return the entries most relevant to ``query``.

        Semantic search when an embedding is available; otherwise the
        highest-confidence / most-recent entries.
        """
        async with self._session_factory() as session:
            repo = ProfileEntryRepository(session)
            if query and self._embeddings.enabled:
                vector = await self._embeddings.embed(query)
                if vector is not None:
                    hits = await repo.semantic_search(user_id, vector, top_k=top_k)
                    if hits:
                        return hits
            return await repo.list_by_user(
                user_id, statuses=("auto", "confirmed"), limit=top_k
            )

    async def recompile_snapshot(self, user_id: UUID) -> None:
        async with self._session_factory() as session:
            entry_repo = ProfileEntryRepository(session)
            profile_repo = ProfileRepository(session)
            profile = await profile_repo.get_or_create(user_id)
            entries = await entry_repo.list_by_user(
                user_id, statuses=("auto", "confirmed"), limit=1000
            )
            triples = [(e.entry_type, e.content, e.confidence) for e in entries]
            snapshot = pm.compile_snapshot(
                basic_info=profile.basic_info or {},
                experiences=profile.experiences or [],
                entries=triples,
            )
            summary = pm.build_summary(snapshot)
            await profile_repo.update_snapshot(
                user_id=user_id, snapshot=snapshot, summary=summary
            )

    async def get_summary_text(self, user_id: UUID) -> str | None:
        """Convenience read of the compiled summary (used as profile_block)."""
        async with self._session_factory() as session:
            profile = await ProfileRepository(session).get_by_user_id(user_id)
            return profile.summary if profile else None

    # ---------- internals ----------

    async def _ingest(self, user_id: UUID) -> dict:
        async with self._session_factory() as session:
            src_repo = ExtractedDataRepository(session)
            rows = await src_repo.list_uningested(user_id)
            if not rows:
                return {"ingested_rows": 0, "created": 0, "updated": 0}

            candidates: list[pm.Candidate] = []
            for row in rows:
                cand = pm.extracted_row_to_candidate(
                    data_type=row.data_type,
                    data_content=row.data_content,
                    source_id=row.generation_id,
                    evidence_ids=[],
                )
                if cand is not None:
                    candidates.append(cand)

            touched = await self._merge_candidates(user_id, candidates, session=session)
            await src_repo.mark_ingested([r.id for r in rows])
            return {"ingested_rows": len(rows), **touched}

    async def _merge_candidates(
        self,
        user_id: UUID,
        candidates: list[pm.Candidate],
        *,
        session=None,
    ) -> dict:
        """Merge candidates into profile_entries (create or corroborate).

        Handles its own session unless one is supplied (so it can share the
        ingest transaction). Embeddings are computed in a batch for new/updated
        entries and best-effort (NULL on failure).
        """
        own_session = session is None
        if own_session:
            session = self._session_factory()
            await session.__aenter__()
        try:
            repo = ProfileEntryRepository(session)
            created = 0
            updated = 0
            # Track entries needing (re)embedding: (entry, text).
            to_embed: list[tuple[ProfileEntry, str]] = []

            for cand in candidates:
                existing = None
                if cand.source_ref:
                    existing = await repo.find_by_source_ref(
                        user_id, cand.source_type, cand.source_ref
                    )
                if existing is None:
                    existing = await repo.find_by_dedup(
                        user_id, cand.entry_type, cand.dedup_key
                    )
                now = datetime.now(UTC)
                if existing is None:
                    entry = ProfileEntry(
                        user_id=user_id,
                        entry_type=cand.entry_type,
                        content=cand.content,
                        dedup_key=cand.dedup_key,
                        source_type=cand.source_type,
                        source_id=cand.source_id,
                        source_ref=cand.source_ref,
                        first_seen_at=now,
                        last_seen_at=now,
                        evidence_ids=list(cand.evidence_ids),
                        occurrences=1,
                        confidence=pm.score_confidence(1, cand.source_type),
                    )
                    repo.add(entry)
                    created += 1
                    text = pm.entry_text_for_embedding(cand.entry_type, cand.content)
                    if text:
                        to_embed.append((entry, text))
                else:
                    # Only bump occurrences when this is a genuinely new
                    # observation. Same source_ref re-arriving (webhook retry,
                    # manual re-sync) MUST NOT inflate confidence.
                    is_same_ref = bool(
                        cand.source_ref
                        and existing.source_ref == cand.source_ref
                    )
                    if not is_same_ref:
                        existing.occurrences += 1
                    existing.content = pm.merge_content(existing.content, cand.content)
                    # Prefer the stronger provenance for scoring.
                    src = _stronger_source(existing.source_type, cand.source_type)
                    existing.source_type = src
                    existing.confidence = pm.score_confidence(existing.occurrences, src)
                    if cand.source_ref and not existing.source_ref:
                        existing.source_ref = cand.source_ref
                    if existing.first_seen_at is None:
                        existing.first_seen_at = now
                    existing.last_seen_at = now
                    merged_ev = list(dict.fromkeys([*existing.evidence_ids, *cand.evidence_ids]))
                    existing.evidence_ids = merged_ev
                    updated += 1
                    text = pm.entry_text_for_embedding(existing.entry_type, existing.content)
                    if text:
                        to_embed.append((existing, text))

            # Flush so new rows get PKs before we attach embeddings.
            await session.flush()
            await self._attach_embeddings(to_embed)
            await session.commit()
            return {"created": created, "updated": updated}
        finally:
            if own_session:
                await session.__aexit__(None, None, None)

    async def _attach_embeddings(self, items: list[tuple[ProfileEntry, str]]) -> None:
        if not items or not self._embeddings.enabled:
            return
        vectors = await self._embeddings.embed_batch([t for _, t in items])
        if vectors is None:
            return
        for (entry, _), vec in zip(items, vectors, strict=False):
            entry.embedding = vec


def _stronger_source(a: str, b: str) -> str:
    order = {"generation": 0, "resume_import": 1, "github": 2, "user_input": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b
