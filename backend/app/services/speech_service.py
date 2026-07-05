"""Speech-to-text service using OpenAI's Whisper API.

Wraps the transcription call and returns plain text. Kept minimal because in
v0.1 voice input is just an alternate route into the existing generate pipeline
— once we have text, everything else reuses the LLM/Agent path.
"""
from __future__ import annotations

import io
import time

from openai import AsyncOpenAI

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


# Whisper API supports: mp3, mp4, mpeg, mpga, m4a, wav, webm
SUPPORTED_AUDIO_EXTENSIONS: frozenset[str] = frozenset(
    {"mp3", "mp4", "mpeg", "mpga", "m4a", "wav", "webm"}
)

# Whisper's per-request limit is 25 MB
MAX_AUDIO_BYTES: int = 25 * 1024 * 1024


class SpeechError(Exception):
    """Base exception for speech transcription failures."""


class WhisperService:
    """Thin async wrapper around OpenAI Whisper transcription."""

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=api_key or settings.openai_api_key or None,
            timeout=60.0,
        )

    async def transcribe(
        self,
        *,
        audio_bytes: bytes,
        filename: str,
        language: str | None = None,
    ) -> str:
        """Transcribe raw audio bytes to text.

        Args:
            audio_bytes: Raw audio file contents.
            filename: Original filename (used to derive Whisper's MIME hint).
            language: ISO-639-1 code, e.g. ``zh`` / ``en``. Defaults to config.

        Raises:
            SpeechError: On any transcription failure or invalid input.
        """
        if not audio_bytes:
            raise SpeechError("empty_audio")
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise SpeechError(f"audio_too_large: {len(audio_bytes)} bytes > 25MB")

        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in SUPPORTED_AUDIO_EXTENSIONS:
            raise SpeechError(
                f"unsupported_format: {ext!r}; supported={sorted(SUPPORTED_AUDIO_EXTENSIONS)}"
            )

        started = time.time()

        # The OpenAI SDK expects a file-like object; wrap bytes in BytesIO and
        # give it a `name` so the SDK sends the right filename in multipart.
        buffer = io.BytesIO(audio_bytes)
        buffer.name = filename

        try:
            result = await self._client.audio.transcriptions.create(
                model=self._settings.whisper_model,
                file=buffer,
                language=language or self._settings.whisper_language or None,
                response_format="text",
            )
        except Exception as e:  # noqa: BLE001
            logger.error("whisper_failed", error=str(e), filename=filename)
            raise SpeechError(f"transcription_failed: {e}") from e

        # `response_format=text` returns a bare string from the SDK.
        text = result if isinstance(result, str) else str(result)
        elapsed_ms = int((time.time() - started) * 1000)
        logger.info(
            "whisper_ok",
            filename=filename,
            audio_bytes=len(audio_bytes),
            text_len=len(text),
            elapsed_ms=elapsed_ms,
        )
        return text.strip()
