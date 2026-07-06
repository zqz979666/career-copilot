"""AnalysisAgent (v1.0): ability assessment / gap analysis."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agents.base import AgentContext, AgentResult, AgentType, BaseAgent
from app.agents.prompt_loader import load_prompt
from app.llm.gateway import LLMConfig, LLMGateway, LLMUsage
from app.llm.json_utils import parse_json_object

ANALYSIS_TASKS: frozenset[str] = frozenset({"ability_assessment", "gap_analysis"})


@dataclass
class AnalysisLLMResult:
    data: dict[str, Any]
    usage: LLMUsage


class AnalysisAgent(BaseAgent):
    agent_type = AgentType.ANALYSIS

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def assess_ability(self, *, input_content: str, profile_block: str) -> AnalysisLLMResult:
        prompt = load_prompt("analysis_assess")
        raw, usage = await self._llm.generate(
            system_prompt=prompt.system,
            user_message=prompt.render(input_content=input_content, profile_block=profile_block),
            config=LLMConfig(temperature=0.2, max_tokens=2500),
            cache_system_prompt=True,
        )
        return AnalysisLLMResult(data=parse_json_object(raw), usage=usage)

    async def execute(self, context: AgentContext) -> AgentResult:
        if context.task_type not in ANALYSIS_TASKS:
            raise ValueError(f"AnalysisAgent.execute unsupported task_type: {context.task_type}")
        result = await self.assess_ability(
            input_content=context.input_content,
            profile_block=context.profile_summary or "",
        )
        return AgentResult(content="", extracted_data=result.data, token_usage=result.usage.to_dict())

    def stream(self, context: AgentContext) -> AsyncGenerator[str, None]:
        raise NotImplementedError("AnalysisAgent produces structured JSON, not a stream")
