"""ResumeAgent — resume generation, JD analysis, match assessment, diagnosis.

Pure LLM-capability unit: it takes already-assembled text context (profile
summary, JD, requirements) and returns structured dicts + token usage. All DB
access / retrieval / persistence is orchestrated by the service layer
(:mod:`app.services.resume_studio_service` / :mod:`app.services.jd_service`),
keeping the Profile Engine as the sole data channel.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from app.agents.base import AgentContext, AgentResult, AgentType, BaseAgent
from app.agents.prompt_loader import load_prompt
from app.llm.gateway import LLMConfig, LLMGateway, LLMUsage
from app.llm.json_utils import parse_json_object
from app.logging_config import get_logger

logger = get_logger(__name__)

RESUME_TASKS: frozenset[str] = frozenset(
    {"resume_generate", "jd_analysis", "resume_diagnose"}
)


@dataclass
class LLMResult:
    data: dict[str, Any]
    usage: LLMUsage


class ResumeAgent(BaseAgent):
    """Resume/JD capabilities. Non-streaming, JSON-structured outputs."""

    agent_type = AgentType.RESUME

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    # ---------- capabilities ----------

    async def generate_resume(
        self, *, profile_block: str, jd_block: str = "", match_block: str = ""
    ) -> LLMResult:
        prompt = load_prompt("resume_generate")
        user_msg = prompt.render(
            profile_block=profile_block, jd_block=jd_block, match_block=match_block
        )
        return await self._json_call(prompt.system, user_msg, max_tokens=4096)

    async def analyze_jd(self, *, jd_text: str) -> LLMResult:
        prompt = load_prompt("jd_analyze")
        user_msg = prompt.render(input_content=jd_text)
        return await self._json_call(prompt.system, user_msg, max_tokens=2048)

    async def match_assessment(
        self, *, profile_block: str, requirements_block: str
    ) -> LLMResult:
        prompt = load_prompt("jd_match")
        user_msg = prompt.render(
            profile_block=profile_block, requirements_block=requirements_block
        )
        return await self._json_call(prompt.system, user_msg, max_tokens=3072)

    async def diagnose_resume(self, *, resume_text: str) -> LLMResult:
        prompt = load_prompt("resume_diagnose")
        user_msg = prompt.render(input_content=resume_text)
        return await self._json_call(prompt.system, user_msg, max_tokens=2048)

    # ---------- internals ----------

    async def _json_call(
        self, system: str, user_msg: str, *, max_tokens: int
    ) -> LLMResult:
        raw, usage = await self._llm.generate(
            system_prompt=system,
            user_message=user_msg,
            config=LLMConfig(temperature=0.3, max_tokens=max_tokens),
            cache_system_prompt=True,
        )
        data = parse_json_object(raw)
        return LLMResult(data=data, usage=usage)

    # ---------- BaseAgent (non-streaming agent) ----------

    async def execute(self, context: AgentContext) -> AgentResult:
        # The Resume agent is normally driven via its typed capabilities above.
        # execute() supports the generic path for completeness (JD analysis).
        if context.task_type == "jd_analysis":
            result = await self.analyze_jd(jd_text=context.input_content)
            return AgentResult(content="", extracted_data=result.data, token_usage=result.usage.to_dict())
        raise ValueError(f"ResumeAgent.execute unsupported task_type: {context.task_type}")

    def stream(self, context: AgentContext) -> AsyncGenerator[str, None]:
        raise NotImplementedError("ResumeAgent produces structured JSON, not a stream")
