"""Profile endpoints: get current profile + upload resume."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.dependencies import DbSession, get_current_user_id, get_resume_service
from app.logging_config import get_logger
from app.models.schemas import ProfileOut, ResumeUploadResponse
from app.repository.profile_repo import ProfileRepository
from app.services.resume_service import ResumeService, ResumeServiceError

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])


@router.get("", response_model=ProfileOut | None)
async def get_profile(
    session: DbSession,
    user_id: UUID = Depends(get_current_user_id),
) -> ProfileOut | None:
    profile = await ProfileRepository(session).get_by_user_id(user_id)
    return ProfileOut.model_validate(profile) if profile else None


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
) -> ResumeUploadResponse:
    """Upload a resume, parse it, and persist the initial Profile.

    Semantics (v0.1): a new upload **replaces** the current profile
    (last-write-wins). Fine-grained merging arrives in v0.5 via the Profile
    Engine's Merger.
    """
    settings = get_settings()
    max_bytes = settings.document_max_upload_bytes

    if resume.size is not None and resume.size > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file_too_large: max={max_bytes} bytes",
        )

    data = await resume.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"file_too_large: max={max_bytes} bytes",
        )

    logger.info(
        "resume_upload_request",
        filename=resume.filename,
        content_type=resume.content_type,
        size=len(data),
    )

    try:
        parsed = await parser.parse(
            data=data,
            filename=resume.filename,
            content_type=resume.content_type,
        )
    except ResumeServiceError as e:
        # Text extraction / LLM structuring failed — surface as 400.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    repo = ProfileRepository(session)
    profile = await repo.upsert_from_resume(
        user_id=user_id,
        basic_info=parsed.basic_info,
        skills=parsed.skills,
        experiences=parsed.experiences,
        # raw_resume_url stays None in v0.1 (no S3 wire-up); v0.5 will fill it.
        raw_resume_url=None,
    )

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
