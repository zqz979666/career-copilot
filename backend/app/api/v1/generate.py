"""SSE streaming generation endpoints (text + voice)."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.middleware.rate_limit import enforce_generate_rate_limit
from app.api.sse import SSE_HEADERS, sse
from app.config import get_settings
from app.dependencies import (
    get_generate_service,
    get_optional_user_id,
    get_speech_service,
)
from app.logging_config import get_logger
from app.models.schemas import GenerateRequest, IntentResponse
from app.services.generate_service import GenerateService
from app.services.speech_service import SpeechError, WhisperService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["generate"])

# Voice input targets the efficiency (streaming) chains only.
VoiceTaskType = Literal[
    "auto", "weekly_report", "monthly_report", "star", "free_format", "promotion"
]


@router.post("/intent", response_model=IntentResponse)
async def classify_intent(
    body: GenerateRequest,
    service: GenerateService = Depends(get_generate_service),
) -> IntentResponse:
    """Master Agent intent classification (rule → Haiku fallback).

    Lets the client preview which chain "auto" would resolve to before
    committing to a streamed generation.
    """
    result = await service.classify_intent(body.input_content)
    return IntentResponse(
        intent=result.intent,
        task_type=result.task_type,
        agent_type=result.agent_type.value,
        confidence=result.confidence,
        method=result.method,
    )


@router.post("/generate", dependencies=[Depends(enforce_generate_rate_limit)])
async def generate(
    body: GenerateRequest,
    user_id: UUID | None = Depends(get_optional_user_id),
    service: GenerateService = Depends(get_generate_service),
) -> StreamingResponse:
    """Stream a completion as SSE.

    Response event stream:
        event: message   data: "<chunk text>"
        ... more messages ...
        event: done      data: {"status": "complete"}
        event: error     data: {"error": "<code>", "message": "..."}
    """
    logger.info(
        "generate_request",
        task_type=body.task_type,
        input_len=len(body.input_content),
        anonymous=user_id is None,
    )

    async def event_stream():
        try:
            async for chunk in service.generate_stream(
                user_id=user_id,
                task_type=body.task_type,
                input_content=body.input_content,
                input_type="voice" if body.voice_mode else "text",
            ):
                yield sse("message", chunk)
            yield sse("done", {"status": "complete"})
        except Exception as e:  # noqa: BLE001
            logger.exception("generate_failed", error=str(e))
            yield sse("error", {"error": type(e).__name__, "message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/generate/voice", dependencies=[Depends(enforce_generate_rate_limit)])
async def generate_voice(
    audio: UploadFile = File(..., description="Audio file: mp3/m4a/wav/webm/mp4/mpga/mpeg"),
    task_type: VoiceTaskType = Form(default="weekly_report"),
    language: str | None = Form(default=None, description="ISO-639-1 (e.g. zh/en); auto-detect if omitted"),
    user_id: UUID | None = Depends(get_optional_user_id),
    service: GenerateService = Depends(get_generate_service),
    speech: WhisperService = Depends(get_speech_service),
) -> StreamingResponse:
    """Voice → transcription → SSE stream.

    Emits an extra ``transcript`` event before the ``message`` chunks so
    clients can display "you said: ..." while the model streams.

    Response event stream:
        event: transcript  data: {"text": "<recognized text>"}
        event: message     data: "<chunk>"  (x N)
        event: done        data: {"status": "complete"}
        event: error       data: {"error": "...", "message": "..."}
    """
    settings = get_settings()

    if audio.size is not None and audio.size > settings.document_max_upload_bytes:
        # Reuse the generic upload cap; Whisper has its own 25MB inner limit too.
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large")

    audio_bytes = await audio.read()

    logger.info(
        "voice_request",
        filename=audio.filename,
        content_type=audio.content_type,
        size=len(audio_bytes),
        task_type=task_type,
        anonymous=user_id is None,
    )

    try:
        transcript = await speech.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.webm",
            language=language,
        )
    except SpeechError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    if not transcript:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "empty_transcript")

    async def event_stream():
        try:
            yield sse("transcript", {"text": transcript})
            async for chunk in service.generate_stream(
                user_id=user_id,
                task_type=task_type,
                input_content=transcript,
                input_type="voice",
            ):
                yield sse("message", chunk)
            yield sse("done", {"status": "complete"})
        except Exception as e:  # noqa: BLE001
            logger.exception("voice_generate_failed", error=str(e))
            yield sse("error", {"error": type(e).__name__, "message": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=SSE_HEADERS)
