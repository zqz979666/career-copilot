"""Tests for the ResumeService JSON post-processing helpers.

The service's parse() flow needs a live LLM call, so here we exercise the
pure helpers (JSON extraction, coercion). End-to-end resume parsing is
verified via curl in manual smoke tests.
"""
from __future__ import annotations

from app.services.resume_service import (
    _ensure_dict,
    _ensure_list_of_dict,
    _ensure_list_of_str,
    _extract_json_block,
    _strip_code_fences,
)


def test_strip_code_fences_json() -> None:
    text = '```json\n{"a": 1}\n```'
    assert _strip_code_fences(text) == '{"a": 1}'


def test_strip_code_fences_bare() -> None:
    text = "```\n{\"x\": 2}\n```"
    assert _strip_code_fences(text) == '{"x": 2}'


def test_extract_json_block_with_prose() -> None:
    text = 'Sure, here is the JSON:\n{"name": "张三", "age": 30}\nHope that helps!'
    assert _extract_json_block(text) == '{"name": "张三", "age": 30}'


def test_ensure_helpers_coerce_bad_input() -> None:
    assert _ensure_dict(None) == {}
    assert _ensure_dict("nope") == {}
    assert _ensure_dict({"k": "v"}) == {"k": "v"}

    assert _ensure_list_of_str(["Python", "", None, "  Go  "]) == ["Python", "Go"]
    assert _ensure_list_of_str("not-a-list") == []

    good = [{"company": "X"}, "junk", None, {"company": "Y"}]
    assert _ensure_list_of_dict(good) == [{"company": "X"}, {"company": "Y"}]
