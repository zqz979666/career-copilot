"""Document ingest API (v1.0)."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.config import get_settings
from app.dependencies import get_current_user_id, get_document_service
from app.services.document_service import DocumentService

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    user_id: UUID = Depends(get_current_user_id),
    svc: DocumentService = Depends(get_document_service),
) -> dict:
    data = await file.read()
    settings = get_settings()
    if len(data) > settings.document_max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large")
    try:
        return await svc.upload(
            user_id=user_id,
            filename=file.filename,
            content_type=file.content_type,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
