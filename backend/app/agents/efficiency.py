"""EfficiencyAgent — v0.1 sole agent implementation.

Owns three chains:
    - weekly_report
    - star
    - free_format

Each chain is a `(prompt template name, model config)` pair. Chains share the
same LLM Gateway and identical streaming/extraction plumbing.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from app.agents.base import AgentContext, AgentResult, AgentType, BaseAgent
from app.agents.prompt_loader import PromptTemplate, load_prompt
from app.llm.gateway import LLMConfig, LLMGateway
from app.logging_config import get_logger

logger = get_logger(__name__)


_TASK_TO_PROMPT: dict[str, str] = {
    "weekly_report": "weekly_report",
    "star": "star",
    "free_format": "free_format",
}


class EfficiencyAgent(BaseAgent):
    """Handles all "work-output rewriting" tasks in v0.1."""

    agent_type = AgentType.EFFICIENCY

    def __init__(self, llm: LLMGateway) -> None:
        self._llm = llm

    # ---------- BaseAgent ----------

    async def execute(self, context: AgentContext) -> AgentResult:
        template = self._resolve_prompt(context.task_type)
        user_msg = template.render_user(
            context.input_content, profile_block=self._profile_block(context)
        )
        text, usage = await self._llm.generate(
            system_prompt=template.system,
            user_message=user_msg,
            config=LLMConfig(),
        )
        return AgentResult(content=text, token_usage=usage.to_dict())

    async def stream(self, context: AgentContext) -> AsyncGenerator[str, None]:
        template = self._resolve_prompt(context.task_type)
        user_msg = template.render_user(
            context.input_content, profile_block=self._profile_block(context)
        )
        logger.info(
            "agent_stream_start",
            agent=self.agent_type.value,
            task_type=context.task_type,
            prompt_version=template.version,
            input_len=len(context.input_content),
        )
        async for chunk in self._llm.stream(
            system_prompt=template.system,
            user_message=user_msg,
            config=LLMConfig(),
        ):
            yield chunk

    # ---------- helpers ----------

    @staticmethod
    def _resolve_prompt(task_type: str) -> PromptTemplate:
        prompt_name = _TASK_TO_PROMPT.get(task_type)
        if prompt_name is None:
            raise ValueError(f"Unsupported task_type: {task_type}")
        return load_prompt(prompt_name)

    @staticmethod
    def _profile_block(context: AgentContext) -> str:
        # v0.1: no profile summary. Kept as a placeholder so v0.5 can drop it in.
        if not context.profile_summary:
            return ""
        return f"背景（个人画像摘要）：\n{context.profile_summary.strip()}"
