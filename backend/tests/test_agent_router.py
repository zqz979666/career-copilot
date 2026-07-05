"""Smoke test for AgentRouter routing rules."""
from __future__ import annotations

import pytest

from app.agents.base import AgentContext, AgentRouter, AgentType, BaseAgent


class DummyAgent(BaseAgent):
    agent_type = AgentType.EFFICIENCY

    async def execute(self, context):  # type: ignore[override]
        raise NotImplementedError

    def stream(self, context):  # type: ignore[override]
        async def _empty():
            if False:
                yield ""
        return _empty()


def _ctx(task_type: str) -> AgentContext:
    return AgentContext(user_id=None, task_type=task_type, input_content="hi")


def test_router_dispatches_known_tasks() -> None:
    router = AgentRouter()
    agent = DummyAgent()
    router.register(agent)
    for task in ("weekly_report", "star", "free_format"):
        assert router.route(_ctx(task)) is agent


def test_router_falls_back_for_unknown_task() -> None:
    router = AgentRouter()
    router.register(DummyAgent())
    # Unknown task_type still resolves to EFFICIENCY (only registered agent).
    assert router.route(_ctx("unknown_task")).agent_type == AgentType.EFFICIENCY


def test_router_raises_when_agent_missing() -> None:
    router = AgentRouter()
    with pytest.raises(LookupError):
        router.route(_ctx("weekly_report"))
