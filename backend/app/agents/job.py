"""JobAgent (v1.0): interview kit + recommendation pitch."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agents.base import AgentContext, AgentResult, AgentType, BaseAgent
from app.agents.prompt_loader import load_prompt
from app.llm.gateway import LLMConfig, LLMGateway, LLMUsage
from app.llm.json_utils import parse_json_object

JOB_TASKS: frozenset[str] = frozenset({"job_kit"})


@dataclass
class JobLLMResult:
    data: dict[str, Any]
    usage: LLMUsage


class JobAgent(BaseAgent):
    agent_type = AgentType.JOB

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    async def build_interview_kit(self, *, profile_block: str, jd_block: str) -> JobLLMResult:
        prompt = load_prompt("job_kit")
        raw, usage = await self._llm.generate(
            system_prompt=prompt.system,
            user_message=prompt.render(profile_block=profile_block, jd_block=jd_block),
            config=LLMConfig(temperature=0.3, max_tokens=3200),
            cache_system_prompt=True,
        )
        return JobLLMResult(data=parse_json_object(raw), usage=usage)

    async def execute(self, context: AgentContext) -> AgentResult:
        if context.task_type not in JOB_TASKS:
            raise ValueError(f"JobAgent.execute unsupported task_type: {context.task_type}")
        result = await self.build_interview_kit(
            profile_block=context.profile_summary or "",
            jd_block=context.input_content,
        )
        return AgentResult(content="", extracted_data=result.data, token_usage=result.usage.to_dict())

    def stream(self, context: AgentContext) -> AsyncGenerator[str, None]:
        raise NotImplementedError("JobAgent produces structured JSON, not a stream")
