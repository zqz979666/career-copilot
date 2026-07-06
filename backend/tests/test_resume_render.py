"""Tests for resume rendering (Markdown/HTML) + JSON utils."""
from __future__ import annotations

import pytest

from app.llm.json_utils import (
    extract_json_block,
    parse_json_object,
    strip_fences,
)
from app.services import resume_render

_SAMPLE = {
    "basic_info": {"name": "张三", "headline": "5 年后端", "email": "z@x.com"},
    "summary": "专注分布式系统的后端工程师。",
    "skills": ["Python", "Kafka"],
    "experiences": [
        {"company": "字节", "title": "高级工程师", "start_date": "2022", "end_date": "至今",
         "bullets": ["主导订单中心分库分表"]}
    ],
    "projects": [
        {"name": "订单中心", "role": "负责人", "summary": "分库分表",
         "highlights": ["QPS 3k→12k"], "tech_stack": ["Redis", "Kafka"]}
    ],
    "education": [{"school": "某大学", "degree": "本科", "major": "计算机"}],
}


def test_render_markdown_contains_sections() -> None:
    md = resume_render.render_markdown(_SAMPLE)
    assert "# 张三" in md
    assert "## 个人简介" in md
    assert "## 技能" in md
    assert "## 工作经历" in md
    assert "订单中心分库分表" in md
    assert "## 项目经历" in md
    assert "QPS 3k→12k" in md
    assert "## 教育经历" in md


def test_render_html_escapes_and_structures() -> None:
    data = dict(_SAMPLE)
    data["summary"] = "<script>alert(1)</script>"
    html = resume_render.render_html(data)
    assert "<h1>张三</h1>" in html
    assert "&lt;script&gt;" in html  # escaped
    assert "<script>alert(1)</script>" not in html


def test_render_markdown_empty_is_safe() -> None:
    md = resume_render.render_markdown({})
    assert "# 姓名" in md


# ---- json utils ----


def test_strip_fences() -> None:
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_block_object_and_array() -> None:
    assert extract_json_block('prefix {"a": 1} suffix') == '{"a": 1}'
    assert extract_json_block("noise [1, 2, 3] tail") == "[1, 2, 3]"


def test_parse_json_object_ok() -> None:
    assert parse_json_object('```json\n{"x": 2}\n```') == {"x": 2}


def test_parse_json_object_rejects_non_object() -> None:
    with pytest.raises(ValueError):
        parse_json_object("[1, 2, 3]")


def test_parse_json_object_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_json_object("not json at all")
