"""Shared helpers for coaxing clean JSON out of LLM responses.

The Efficiency / Resume agents ask the model for strict JSON, but models
occasionally wrap it in ```json fences``` or add prose. These helpers strip
that noise and parse the first balanced object/array. Extracted here so the
extraction / resume / JD services share one implementation.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_fences(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def extract_json_block(text: str) -> str:
    """Return the outermost ``{...}`` or ``[...]`` block from a noisy response."""
    text = strip_fences(text)
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        return text
    # Find the widest balanced object; fall back to array bounds.
    obj_start, obj_end = text.find("{"), text.rfind("}")
    arr_start, arr_end = text.find("["), text.rfind("]")
    if obj_start != -1 and obj_end > obj_start:
        return text[obj_start : obj_end + 1]
    if arr_start != -1 and arr_end > arr_start:
        return text[arr_start : arr_end + 1]
    return text


def parse_json(text: str) -> Any:
    """Parse JSON from a possibly-noisy LLM response. Raises ``ValueError``."""
    try:
        return json.loads(extract_json_block(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"invalid_json_from_llm: {e}") from e


def parse_json_object(text: str) -> dict[str, Any]:
    parsed = parse_json(text)
    if not isinstance(parsed, dict):
        raise ValueError("expected_json_object")
    return parsed
