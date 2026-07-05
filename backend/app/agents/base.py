"""Agent Protocol — the abstraction predefined in v0.1 for future multi-Agent orchestration.

v0.1 ships exactly one implementation (:class:`EfficiencyAgent`) with three chains
(weekly_report / star / free_format). The router remains rule-based; v0.5+ upgrades
it into a Master Agent with LLM-fallback intent classification.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentType(str, Enum):
    EFFICIENCY = "efficiency"
    RESUME = "resume"
    ANALYSIS = "analysis"
    JOB = "job"


@dataclass
class AgentContext:
    """Unified execution context passed to every Agent."""

    user_id: str | None
    task_type: str
    input_content: str
    profile_summary: str | None = None
    conversation_history: list[dict] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """Unified result returned by every Agent."""

    content: str
    extracted_data: dict | None = None
    evidence_chain: list | None = None
    token_usage: dict | None = None
    confidence: float = 1.0


class BaseAgent(ABC):
    """Base class for all Agents.

    v0.1 only exercises :meth:`stream`; :meth:`execute` is available for
    non-streaming callers (e.g. background tasks, evals).
    """

    agent_type: AgentType

    @abstractmethod
    async def execute(self, context: AgentContext) -> AgentResult: ...

    @abstractmethod
    def stream(self, context: AgentContext) -> AsyncGenerator[str, None]: ...

    async def extract_side_effects(
        self, context: AgentContext, result: AgentResult
    ) -> dict:
        """Optional: extract structured facts as a side effect. Default is no-op."""
        return {}


class AgentRouter:
    """Simple rule-based router (v0.1). Replaced by Master Agent in v0.5+."""

    _TASK_TO_TYPE: dict[str, AgentType] = {
        "weekly_report": AgentType.EFFICIENCY,
        "star": AgentType.EFFICIENCY,
        "free_format": AgentType.EFFICIENCY,
    }

    def __init__(self) -> None:
        self._agents: dict[AgentType, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_type] = agent

    def route(self, context: AgentContext) -> BaseAgent:
        agent_type = self._TASK_TO_TYPE.get(context.task_type)
        if agent_type is None:
            # Fallback: whatever Efficiency does for `free_format`
            agent_type = AgentType.EFFICIENCY
        if agent_type not in self._agents:
            raise LookupError(f"No agent registered for type {agent_type.value}")
        return self._agents[agent_type]
