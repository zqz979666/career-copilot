"""Screenshot OCR + structuring via Claude Vision (v0.5 P1).

Takes an uploaded image (Jira board / task list / doc snippet) and returns a
structured task list. Best-effort: on any failure the caller surfaces a 400 and
the product nudges the user to paste text instead.
"""
from __future__ import annotations

from app.agents.prompt_loader import load_prompt
from app.config import get_settings
from app.llm.gateway import LLMConfig, LLMGateway
from app.llm.json_utils import parse_json_object
from app.logging_config import get_logger

logger = get_logger(__name__)

_SUPPORTED_MEDIA: dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


class ScreenshotError(Exception):
    """Raised on unsupported/oversized image or parse failure."""


class ScreenshotService:
    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm
        self._settings = get_settings()

    async def parse(
        self, *, image_bytes: bytes, filename: str | None, content_type: str | None
    ) -> dict:
        if not image_bytes:
            raise ScreenshotError("empty_image")
        if len(image_bytes) > self._settings.vision_max_image_bytes:
            raise ScreenshotError("image_too_large")

        media_type = self._resolve_media_type(filename, content_type)
        prompt = load_prompt("screenshot_parse")

        try:
            raw, usage = await self._llm.generate_vision(
                system_prompt=prompt.system,
                user_message=prompt.render(),
                image_bytes=image_bytes,
                media_type=media_type,
                config=LLMConfig(model=self._settings.vision_model, temperature=0.0, max_tokens=1500),
            )
        except Exception as e:  # noqa: BLE001
            logger.error("screenshot_vision_failed", error=str(e))
            raise ScreenshotError(f"vision_failed: {e}") from e

        try:
            data = parse_json_object(raw)
        except ValueError as e:
            raise ScreenshotError(str(e)) from e

        tasks = data.get("tasks") if isinstance(data.get("tasks"), list) else []
        return {
            "summary": str(data.get("summary", "")),
            "tasks": tasks,
            "token_usage": usage.to_dict(),
        }

    @staticmethod
    def _resolve_media_type(filename: str | None, content_type: str | None) -> str:
        if content_type and content_type.startswith("image/"):
            return content_type
        if filename and "." in filename:
            ext = filename.rsplit(".", 1)[-1].lower()
            if ext in _SUPPORTED_MEDIA:
                return _SUPPORTED_MEDIA[ext]
        raise ScreenshotError(f"unsupported_image: filename={filename!r} type={content_type!r}")
