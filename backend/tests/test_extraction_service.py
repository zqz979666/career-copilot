"""Tests for ExtractionService's pure post-processing.

The LLM call itself is out of scope — we only cover:
    1. JSON extraction from noisy responses
    2. Row-building coerces junk into empty output rather than crashing
"""
from __future__ import annotations

from uuid import uuid4

from app.services.extraction_service import (
    ExtractionService,
    _extract_json,
    _strip_fences,
)


def test_strip_fences() -> None:
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_with_prose() -> None:
    text = 'Sure, here is the JSON:\n{"projects": []}\nAll done.'
    assert _extract_json(text) == '{"projects": []}'


def test_build_rows_ignores_junk_shapes() -> None:
    user_id = uuid4()
    gen_id = uuid4()
    payload = {
        "projects": "not-a-list",  # ignored
        "skills": ["Python", "", None, "  Go  ", 42],
        "achievements": [
            {"summary": "上线推荐算法", "metric": "QPS +30%"},
            {"nope": "no summary"},  # dropped
            "not a dict",  # dropped
        ],
        "tech_stack": ["PostgreSQL", "Redis"],
    }
    rows = ExtractionService._build_rows(
        user_id=user_id, generation_id=gen_id, payload=payload
    )
    types = [r.data_type for r in rows]
    assert types.count("skill") == 2
    # "Go" is stripped and kept; "Python" kept; empty/None/int dropped
    skills = {r.data_content["name"] for r in rows if r.data_type == "skill"}
    assert skills == {"Python", "Go"}
    assert types.count("achievement") == 1
    assert types.count("tech_stack") == 2
    assert "project" not in types


def test_build_rows_all_empty() -> None:
    rows = ExtractionService._build_rows(
        user_id=uuid4(),
        generation_id=uuid4(),
        payload={"projects": [], "skills": [], "achievements": [], "tech_stack": []},
    )
    assert rows == []
