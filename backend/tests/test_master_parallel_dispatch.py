"""Tests for MasterAgent.dispatch_parallel (v0.8).

Contract:

- When ``MASTER_PARALLEL_ENABLED`` is false, only the primary runs and
  ``extras`` is empty regardless of secondary task types requested.
- When enabled, primary + extras run concurrently and results are keyed
  by ``task_type``.
- A failing extra agent MUST NOT block or affect the primary result.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest

from app.agents.base import AgentContext, AgentResult, AgentType, BaseAgent
from app.agents.master import MasterAgent
from app.config import get_settings


class _FakeAgent(BaseAgent):
    """Deterministic BaseAgent used to observe dispatch order + errors."""

    def __init__(self, agent_type: AgentType, label: str, *, fail: bool = False) -> None:
        self.agent_type = agent_type
        self._label = label
        self._fail = fail
        self.calls: list[str] = []

    async def execute(self, context: AgentContext) -> AgentResult:  # type: ignore[override]
        self.calls.append(context.task_type)
        await asyncio.sleep(0)  # yield so parallelism is observable
        if self._fail:
            raise RuntimeError("boom")
        return AgentResult(content=f"{self._label}:{context.task_type}")

    def stream(self, context: AgentContext) -> AsyncGenerator[str, None]:  # type: ignore[override]
        raise NotImplementedError


def _make_master(*, efficiency_fail: bool = False, resume_fail: bool = False) -> tuple[
    MasterAgent, _FakeAgent, _FakeAgent
]:
    master = MasterAgent(llm=None)
    eff = _FakeAgent(AgentType.EFFICIENCY, "eff", fail=efficiency_fail)
    res = _FakeAgent(AgentType.RESUME, "res", fail=resume_fail)
    master.register(eff)
    master.register(res)
    return master, eff, res


@pytest.fixture(autouse=True)
def _restore_flag():
    settings = get_settings()
    original = settings.master_parallel_enabled
    yield
    settings.master_parallel_enabled = original


async def test_dispatch_parallel_flag_off_skips_extras() -> None:
    get_settings().master_parallel_enabled = False
    master, eff, res = _make_master()
    ctx = AgentContext(user_id=None, task_type="weekly_report", input_content="本周做了A、B、C")

    result = await master.dispatch_parallel(ctx, extras_task_types=["resume_generate"])

    assert result.primary.content == "eff:weekly_report"
    assert result.extras == {}
    assert eff.calls == ["weekly_report"]
    assert res.calls == []  # extras suppressed


async def test_dispatch_parallel_runs_primary_plus_extras() -> None:
    get_settings().master_parallel_enabled = True
    master, eff, res = _make_master()
    ctx = AgentContext(user_id=None, task_type="weekly_report", input_content="x")

    result = await master.dispatch_parallel(
        ctx, extras_task_types=["resume_generate", "weekly_report"]  # dup pruned
    )

    assert result.primary.content == "eff:weekly_report"
    assert set(result.extras.keys()) == {"resume_generate"}
    assert result.extras["resume_generate"].content == "res:resume_generate"
    # Efficiency ran once (primary), Resume ran once (extra).
    assert eff.calls == ["weekly_report"]
    assert res.calls == ["resume_generate"]


async def test_dispatch_parallel_extra_failure_does_not_break_primary() -> None:
    get_settings().master_parallel_enabled = True
    master, eff, res = _make_master(resume_fail=True)
    ctx = AgentContext(user_id=None, task_type="weekly_report", input_content="x")

    result = await master.dispatch_parallel(ctx, extras_task_types=["resume_generate"])

    # Primary succeeded, failing extra silently omitted.
    assert result.primary.content == "eff:weekly_report"
    assert result.extras == {}
