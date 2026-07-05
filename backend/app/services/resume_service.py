"""Resume parsing service.

Pipeline:
    raw file bytes
        │
        ▼
    document.parser.extract_resume_text()  ── plain text
        │
        ▼
    LLMGateway.generate() with resume_parser prompt   ── JSON
        │
        ▼
    parsed dict (basic_info / skills / experiences / education)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.agents.prompt_loader import load_prompt
from app.config import get_settings
from app.document.parser import (
    DocumentParseError,
    ResumeText,
    extract_resume_text,
)
from app.llm.gateway import LLMConfig, LLMGateway
from app.logging_config import get_logger

logger = get_logger(__name__)


class ResumeServiceError(Exception):
    """Raised when the pipeline can't produce a usable profile draft."""


@dataclass
class ParsedResume:
    basic_info: dict[str, Any] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)
    experiences: list[dict[str, Any]] = field(default_factory=list)
    education: list[dict[str, Any]] = field(default_factory=list)
    source_format: str = ""
    source_page_count: int | None = None
    source_chars: int = 0
    token_usage: dict | None = None

    def to_profile_fields(self) -> dict[str, Any]:
        """Shape returned by :meth:`ResumeService.parse` for repo upsert."""
        return {
            "basic_info": self.basic_info,
            "skills": self.skills,
            "experiences": self.experiences,
        }


_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _strip_code_fences(text: str) -> str:
    """Best-effort strip of ```json ... ``` fences the model sometimes emits."""
    return _JSON_FENCE_RE.sub("", text).strip()


def _extract_json_block(text: str) -> str:
    """Pull the first `{...}` block out of a possibly-noisy LLM response."""
    text = _strip_code_fences(text)
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


class ResumeService:
    """Two-stage resume parser: text extraction + LLM structuring."""

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm
        self._settings = get_settings()

    async def parse(
        self,
        *,
        data: bytes,
        filename: str | None,
        content_type: str | None,
    ) -> ParsedResume:
        # 1. Local text extraction
        try:
            resume_text: ResumeText = extract_resume_text(
                data=data, filename=filename, content_type=content_type
            )
        except DocumentParseError as e:
            raise ResumeServiceError(str(e)) from e

        # Cap the payload sent to the LLM to control cost / stay within window.
        max_chars = self._settings.document_max_chars
        text = resume_text.text[:max_chars]
        truncated = len(resume_text.text) > max_chars

        logger.info(
            "resume_extract_ok",
            format=resume_text.format,
            page_count=resume_text.page_count,
            chars=len(resume_text.text),
            truncated=truncated,
        )

        # 2. LLM structuring
        prompt = load_prompt("resume_parser")
        user_message = prompt.render_user(text)

        try:
            raw, usage = await self._llm.generate(
                system_prompt=prompt.system,
                user_message=user_message,
                # temperature 0: deterministic structuring
                config=LLMConfig(temperature=0.0),
                cache_system_prompt=True,
            )
        except Exception as e:  # noqa: BLE001
            logger.error("resume_llm_failed", error=str(e))
            raise ResumeServiceError(f"llm_call_failed: {e}") from e

        # 3. Parse JSON
        json_block = _extract_json_block(raw)
        try:
            parsed: dict[str, Any] = json.loads(json_block)
        except json.JSONDecodeError as e:
            logger.error("resume_json_invalid", preview=raw[:400], error=str(e))
            raise ResumeServiceError(f"invalid_json_from_llm: {e}") from e

        return ParsedResume(
            basic_info=_ensure_dict(parsed.get("basic_info")),
            skills=_ensure_list_of_str(parsed.get("skills")),
            experiences=_ensure_list_of_dict(parsed.get("experiences")),
            education=_ensure_list_of_dict(parsed.get("education")),
            source_format=resume_text.format,
            source_page_count=resume_text.page_count,
            source_chars=len(resume_text.text),
            token_usage=usage.to_dict(),
        )


# ---------- lightweight coercion helpers ----------


def _ensure_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if v is not None and str(v).strip()]


def _ensure_list_of_dict(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]
