"""Tests for the Master Agent rule-based intent classification + routing."""
from __future__ import annotations

import pytest

from app.agents.base import AgentContext, AgentType
from app.agents.efficiency import EfficiencyAgent
from app.agents.master import MasterAgent
from app.agents.resume import ResumeAgent


class _StubLLM:
    """Minimal stand-in; rule stage should never reach it in these tests."""


def _master() -> MasterAgent:
    master = MasterAgent(llm=None)
    master.register(EfficiencyAgent(llm=_StubLLM()))  # type: ignore[arg-type]
    master.register(ResumeAgent(llm=_StubLLM()))  # type: ignore[arg-type]
    return master


@pytest.mark.parametrize(
    ("text", "expected_task"),
    [
        ("帮我写这周的周报", "weekly_report"),
        ("汇总这个月的工作做个月报", "monthly_report"),
        ("我要准备晋升答辩材料", "promotion"),
        ("解析一下这个 PR", "pr_parse"),
        ("这是会议纪要，帮我提取", "meeting_parse"),
        ("帮我生成一份简历", "resume_generate"),
        ("分析下这个 JD 的匹配度", "jd_analysis"),
        ("把这段经历整理成 STAR", "star"),
    ],
)
def test_rule_classification(text: str, expected_task: str) -> None:
    result = _master().classify_rule(text)
    assert result is not None
    assert result.task_type == expected_task
    assert result.method == "rule"


def test_rule_miss_returns_none() -> None:
    assert _master().classify_rule("今天天气不错") is None


async def test_classify_falls_back_to_default_without_llm() -> None:
    # No rule match + no LLM → safe default free_format.
    result = await _master().classify("今天天气不错")
    assert result.task_type == "free_format"
    assert result.method == "default"


def test_route_by_task_type() -> None:
    master = _master()
    eff_ctx = AgentContext(user_id=None, task_type="weekly_report", input_content="x")
    resume_ctx = AgentContext(user_id=None, task_type="jd_analysis", input_content="x")
    assert master.route(eff_ctx).agent_type == AgentType.EFFICIENCY
    assert master.route(resume_ctx).agent_type == AgentType.RESUME


def test_route_unknown_task_falls_back_to_efficiency() -> None:
    master = _master()
    ctx = AgentContext(user_id=None, task_type="totally_unknown", input_content="x")
    assert master.route(ctx).agent_type == AgentType.EFFICIENCY
