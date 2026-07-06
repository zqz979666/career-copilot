"""Resume Studio endpoints — generate / manage / diagnose / export resumes."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.dependencies import get_current_user_id, get_resume_studio_service
from app.logging_config import get_logger
from app.models.schemas import (
    ResumeDiagnoseRequest,
    ResumeGenerateRequest,
    ResumeList,
    ResumeOut,
    ResumeUpdateRequest,
)
from app.services import resume_render
from app.services.resume_studio_service import (
    NoProfileDataError,
    ResumeLimitError,
    ResumeStudioService,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/resumes", tags=["resumes"])


@router.post("", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
async def generate_resume(
    body: ResumeGenerateRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> ResumeOut:
    """Generate a resume from the user's Profile (optionally tailored to a JD)."""
    try:
        resume = await svc.generate(user_id=user_id, title=body.title, jd_text=body.jd_text)
    except NoProfileDataError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ResumeLimitError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    return ResumeOut.model_validate(resume)


@router.get("", response_model=ResumeList)
async def list_resumes(
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> ResumeList:
    rows = await svc.list(user_id)
    return ResumeList(items=[ResumeOut.model_validate(r) for r in rows], total=len(rows))


@router.post("/diagnose")
async def diagnose_resume(
    body: ResumeDiagnoseRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> dict:
    """Diagnose an arbitrary resume text: multi-dim score + improvements."""
    return await svc.diagnose(resume_text=body.resume_text)


@router.get("/{resume_id}", response_model=ResumeOut)
async def get_resume(
    resume_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> ResumeOut:
    resume = await svc.get(user_id, resume_id)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resume_not_found")
    return ResumeOut.model_validate(resume)


@router.patch("/{resume_id}", response_model=ResumeOut)
async def update_resume(
    resume_id: UUID,
    body: ResumeUpdateRequest,
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> ResumeOut:
    if body.title is None and body.content is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty_update")
    resume = await svc.update(
        user_id=user_id, resume_id=resume_id, title=body.title, content=body.content
    )
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resume_not_found")
    return ResumeOut.model_validate(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: UUID,
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> Response:
    ok = await svc.delete(user_id, resume_id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resume_not_found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{resume_id}/export")
async def export_resume(
    resume_id: UUID,
    fmt: str = Query(default="markdown", pattern="^(markdown|html|pdf)$"),
    user_id: UUID = Depends(get_current_user_id),
    svc: ResumeStudioService = Depends(get_resume_studio_service),
) -> Response:
    """Export a resume as Markdown / HTML / PDF.

    PDF requires WeasyPrint (``pip install '.[pdf]'`` + system libs); when it is
    unavailable the endpoint returns 503 and clients fall back to html/markdown.
    """
    resume = await svc.get(user_id, resume_id)
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "resume_not_found")

    content = resume.content or {}
    if fmt == "markdown":
        return PlainTextResponse(resume_render.render_markdown(content))
    if fmt == "html":
        return HTMLResponse(resume_render.render_html(content))
    # pdf
    try:
        pdf_bytes = resume_render.render_pdf(content)
    except resume_render.PdfUnavailableError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from e
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="resume-{resume_id}.pdf"'},
    )
