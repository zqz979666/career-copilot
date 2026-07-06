"""Tests for JD profile-block assembly + prompt template rendering."""
from __future__ import annotations

from dataclasses import dataclass

from app.agents.prompt_loader import load_prompt
from app.services.jd_service import JDService, build_profile_block


@dataclass
class _FakeEntry:
    entry_type: str
    content: dict


def test_build_profile_block_composes_sections() -> None:
    entries = [
        _FakeEntry("skill", {"name": "Python"}),
        _FakeEntry("tech", {"name": "Kafka"}),
        _FakeEntry("project", {"name": "订单中心", "summary": "分库分表"}),
        _FakeEntry("achievement", {"summary": "QPS 提升", "metric": "3k→12k"}),
    ]
    block = build_profile_block("定位：资深后端", entries)
    assert "定位：资深后端" in block
    assert "Python" in block and "Kafka" in block
    assert "订单中心" in block
    assert "QPS 提升" in block and "3k→12k" in block


def test_build_profile_block_empty() -> None:
    assert build_profile_block(None, []) == ""


def test_requirements_block_marks_core_and_implicit() -> None:
    analysis = {
        "core_requirements": ["3年后端经验", "熟悉分布式"],
        "implicit_requirements": ["抗压能力强"],
    }
    block = JDService._requirements_block(analysis)
    assert "[核心] 3年后端经验" in block
    assert "[隐含] 抗压能力强" in block


def test_prompt_render_multi_placeholder() -> None:
    prompt = load_prompt("resume_generate")
    rendered = prompt.render(
        profile_block="PROFILE_X", jd_block="JD_Y", match_block="MATCH_Z"
    )
    assert "PROFILE_X" in rendered
    assert "JD_Y" in rendered
    assert "MATCH_Z" in rendered
    # JSON schema braces in the *system* prompt must be untouched / present.
    assert '"basic_info"' in prompt.system


def test_prompt_render_ignores_unknown_tokens() -> None:
    prompt = load_prompt("weekly_report")
    rendered = prompt.render(input_content="我的工作", profile_block="")
    assert "我的工作" in rendered


def test_all_v05_prompts_load() -> None:
    for name in (
        "monthly_report",
        "promotion",
        "pr_parse",
        "meeting_parse",
        "resume_generate",
        "jd_analyze",
        "jd_match",
        "resume_diagnose",
        "screenshot_parse",
        "intent_classify",
        "analysis_assess",
        "job_kit",
    ):
        tpl = load_prompt(name)
        assert tpl.system.strip()
        assert tpl.user_template.strip()
