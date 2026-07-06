"""Profile endpoints: profile + resume upload + Profile Engine v0.5.

v0.5 adds the Profile Engine surface:
    - compiled snapshot / summary
    - fine-grained entries (view / confirm / reject / batch-confirm)
    - JSON export
    - manual rebuild (ingest pending extracted_data → recompile)
and a screenshot OCR entry point.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.dependencies import (
    DbSession,
    get_current_user_id,
    get_profile_engine,
    get_resume_service,
    get_screenshot_service,
)
from app.logging_config import get_logger
from app.models.schemas import (
    BatchEntryConfirmRequest,
    BatchEntryConfirmResponse,
    EntryStatusUpdateRequest,
    ProfileEntriesList,
    ProfileEntryOut,
    ProfileOut,
    ProfileSnapshotOut,
    ResumeUploadResponse,
    ScreenshotParseResponse,
)
from app.repository.profile_entry_repo import ProfileEntryRepository
from app.repository.profile_repo import ProfileRepository
from app.services.profile_engine import ProfileEngine
from app.services.resume_service import ResumeService, ResumeServiceError
from app.services.screenshot_service import ScreenshotError, ScreenshotService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("", response_model=ProfileOut | None)
async def get_profile(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> ProfileOut | None:
    profile = await ProfileRepository(session).get_by_user_id(user_id)
    return ProfileOut.model_validate(profile) if profile else None


@router.get("/snapshot", response_model=ProfileSnapshotOut)
async def get_snapshot(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> ProfileSnapshotOut:
    """Return the Profile Engine's compiled snapshot + summary."""
    profile = await ProfileRepository(session).get_by_user_id(user_id)
    entry_count = await ProfileEntryRepository(session).count_by_user(user_id)
    if profile is None:
        return ProfileSnapshotOut(user_id=user_id, version=0, entry_count=entry_count)
    return ProfileSnapshotOut(
        user_id=user_id,
        version=profile.version,
        summary=profile.summary,
        snapshot=profile.snapshot or {},
        entry_count=entry_count,
    )


@router.get("/entries", response_model=ProfileEntriesList)
async def list_entries(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
    entry_type: str | None = None,
    status_filter: str | None = None,
) -> ProfileEntriesList:
    """List fine-grained profile entries (optionally filtered)."""
    statuses = (status_filter,) if status_filter else None
    rows = await ProfileEntryRepository(session).list_by_user(
        user_id, entry_type=entry_type, statuses=statuses, limit=500
    )
    return ProfileEntriesList(
        items=[ProfileEntryOut.model_validate(r) for r in rows], total=len(rows)
    )


@router.patch("/entries/{entry_id}", response_model=ProfileEntryOut)
async def update_entry_status(
    entry_id: UUID,
    body: EntryStatusUpdateRequest,
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
    engine: ProfileEngine = Depends(get_profile_engine),
) -> ProfileEntryOut:
    """Confirm or reject a single entry, then recompile the snapshot."""
    repo = ProfileEntryRepository(session)
    entry = await repo.get_owned(entry_id, user_id)
    if entry is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entry_not_found")
    if body.status == "confirmed":
        entry.confidence = max(entry.confidence, 0.95)
    updated = await repo.update_status(entry, body.status)
    await engine.recompile_snapshot(user_id)
    return ProfileEntryOut.model_validate(updated)


@router.post("/entries/confirm", response_model=BatchEntryConfirmResponse)
async def batch_confirm_entries(
    body: BatchEntryConfirmRequest,
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
    engine: ProfileEngine = Depends(get_profile_engine),
) -> BatchEntryConfirmResponse:
    """Batch confirm/reject entries (data-confirmation page), then recompile."""
    repo = ProfileEntryRepository(session)
    confirmed = 0
    rejected = 0
    for eid in body.confirmed_ids:
        entry = await repo.get_owned(eid, user_id)
        if entry is not None:
            entry.confidence = max(entry.confidence, 0.95)
            await repo.update_status(entry, "confirmed")
            confirmed += 1
    for eid in body.rejected_ids:
        entry = await repo.get_owned(eid, user_id)
        if entry is not None:
            await repo.update_status(entry, "rejected")
            rejected += 1
    if confirmed or rejected:
        await engine.recompile_snapshot(user_id)
    return BatchEntryConfirmResponse(confirmed=confirmed, rejected=rejected)


@router.post("/rebuild", response_model=ProfileSnapshotOut)
async def rebuild_profile(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
    engine: ProfileEngine = Depends(get_profile_engine),
) -> ProfileSnapshotOut:
    """Force-ingest pending extracted_data and recompile the snapshot."""
    await engine.ingest_and_recompile(user_id)
    profile = await ProfileRepository(session).get_by_user_id(user_id)
    entry_count = await ProfileEntryRepository(session).count_by_user(user_id)
    if profile is None:
        return ProfileSnapshotOut(user_id=user_id, version=0, entry_count=entry_count)
    return ProfileSnapshotOut(
        user_id=user_id,
        version=profile.version,
        summary=profile.summary,
        snapshot=profile.snapshot or {},
        entry_count=entry_count,
    )


@router.get("/export")
async def export_profile(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> dict:
    """Export the full profile (snapshot + all entries) as JSON."""
    profile = await ProfileRepository(session).get_by_user_id(user_id)
    entries = await ProfileEntryRepository(session).list_by_user(user_id, limit=2000)
    return {
        "user_id": str(user_id),
        "version": profile.version if profile else 0,
        "summary": profile.summary if profile else None,
        "snapshot": (profile.snapshot if profile else {}) or {},
        "entries": [
            {
                "id": str(e.id),
                "entry_type": e.entry_type,
                "content": e.content,
                "confidence": e.confidence,
                "status": e.status,
                "source_type": e.source_type,
                "occurrences": e.occurrences,
            }
            for e in entries
        ],
    }


@router.post(
    "/resume",
    response_model=ResumeUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_resume(
    session: DbSession,
    resume: UploadFile = File(..., description="Resume file: PDF / DOCX / TXT"),
    user_id: UUID = Depends(get_current_user_id),
    parser: ResumeService = Depends(get_resume_service),
    engine: ProfileEngine = Depends(get_profile_engine),
) -> ResumeUploadResponse:
    """Upload a resume, parse it, persist the Profile, and seed the Profile Engine.

    v0.5: in addition to the last-write-wins resume snapshot, parsed skills /
    companies / bullets are folded into ``profile_entries`` (high confidence,
    source ``resume_import``) so they participate in retrieval + matching.
    """
    settings = get_settings()
    max_bytes = settings.document_max_upload_bytes

    if resume.size is not None and resume.size > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file_too_large: max={max_bytes} bytes"
        )

    data = await resume.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"file_too_large: max={max_bytes} bytes"
        )

    logger.info(
        "resume_upload_request",
        filename=resume.filename,
        content_type=resume.content_type,
        size=len(data),
    )

    try:
        parsed = await parser.parse(
            data=data, filename=resume.filename, content_type=resume.content_type
        )
    except ResumeServiceError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    repo = ProfileRepository(session)
    profile = await repo.upsert_from_resume(
        user_id=user_id,
        basic_info=parsed.basic_info,
        skills=parsed.skills,
        experiences=parsed.experiences,
        raw_resume_url=None,
    )

    # Seed the Profile Engine (entries + embeddings + recompiled snapshot).
    try:
        await engine.seed_from_resume(
            user_id,
            {
                "skills": parsed.skills,
                "experiences": parsed.experiences,
                "basic_info": parsed.basic_info,
            },
        )
        await session.refresh(profile)
    except Exception as e:  # noqa: BLE001
        logger.warning("resume_profile_seed_failed", error=str(e))

    populated = sum(
        1
        for field_value in (
            parsed.basic_info,
            parsed.skills,
            parsed.experiences,
            parsed.education,
        )
        if field_value
    )

    return ResumeUploadResponse(
        profile=ProfileOut.model_validate(profile),
        source_format=parsed.source_format,
        source_page_count=parsed.source_page_count,
        source_chars=parsed.source_chars,
        extracted_fields=populated,
        token_usage=parsed.token_usage,
    )


@router.post("/screenshot", response_model=ScreenshotParseResponse)
async def parse_screenshot(
    image: UploadFile = File(..., description="Screenshot: png/jpg/webp"),
    user_id: UUID = Depends(get_current_user_id),
    svc: ScreenshotService = Depends(get_screenshot_service),
) -> ScreenshotParseResponse:
    """Screenshot OCR + structuring (Jira board / task list → tasks)."""
    data = await image.read()
    try:
        result = await svc.parse(
            image_bytes=data, filename=image.filename, content_type=image.content_type
        )
    except ScreenshotError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return ScreenshotParseResponse(**result)
