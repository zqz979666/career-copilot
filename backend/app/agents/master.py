"""Master Agent — intent router + task dispatcher (v0.5 → v0.8).

Upgrades v0.1's hard-coded :class:`AgentRouter` into a two-stage intent
classifier:

    1. Rule stage  — fast regex table (covers the common phrasings).
    2. LLM fallback — Claude Haiku classifies when no rule matches.

v0.8 also enables **parallel sub-agent dispatch** via :meth:`dispatch_parallel`:
when a request can be reasonably handled by more than one specialised agent
(e.g. "帮我写周报同时也把这次经历加进简历"), we fan out to both and merge the
results, capped by the ``MASTER_PARALLEL_ENABLED`` flag.

The Master Agent keeps :meth:`route` (sync, task_type → Agent) so the existing
streaming ``GenerateService`` needs no changes, and adds :meth:`classify`
(async) used when the client sends ``task_type="auto"`` or the free-text entry
point needs disambiguation.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from app.agents.base import AgentContext, AgentResult, AgentType, BaseAgent
from app.agents.analysis import ANALYSIS_TASKS
from app.agents.efficiency import EFFICIENCY_TASKS
from app.agents.job import JOB_TASKS
from app.agents.resume import RESUME_TASKS
from app.config import get_settings
from app.llm.gateway import LLMConfig, LLMGateway
from app.llm.json_utils import parse_json_object
from app.logging_config import get_logger

logger = get_logger(__name__)


# intent → (task_type, agent_type). task_type feeds the concrete chain.
_INTENT_TABLE: dict[str, tuple[str, AgentType]] = {
    "record_weekly": ("weekly_report", AgentType.EFFICIENCY),
    "record_monthly": ("monthly_report", AgentType.EFFICIENCY),
    "record_star": ("star", AgentType.EFFICIENCY),
    "record_promotion": ("promotion", AgentType.EFFICIENCY),
    "record_pr": ("pr_parse", AgentType.EFFICIENCY),
    "record_meeting": ("meeting_parse", AgentType.EFFICIENCY),
    "free_format": ("free_format", AgentType.EFFICIENCY),
    "resume_generate": ("resume_generate", AgentType.RESUME),
    "jd_analysis": ("jd_analysis", AgentType.RESUME),
    "ability_assessment": ("ability_assessment", AgentType.ANALYSIS),
    "interview_kit": ("job_kit", AgentType.JOB),
}

# Ordered rule table (first match wins). Mirrors the v0.5 spec intent_rules.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"月报|月度|这个月|本月"), "record_monthly"),
    (re.compile(r"周报|本周|这周|这一周"), "record_weekly"),
    (re.compile(r"晋升|答辩|职级|promotion"), "record_promotion"),
    (re.compile(r"\bPR\b|commit|合并请求|代码评审|code ?review", re.IGNORECASE), "record_pr"),
    (re.compile(r"会议|纪要|meeting|同步会|周会|评审会"), "record_meeting"),
    (re.compile(r"简历|resume|\bCV\b", re.IGNORECASE), "resume_generate"),
    (re.compile(r"\bJD\b|岗位|职位|招聘|投递|匹配度", re.IGNORECASE), "jd_analysis"),
    (re.compile(r"能力评估|雷达图|差距分析|成长报告"), "ability_assessment"),
    (re.compile(r"面试题|面经|面试准备|interview"), "interview_kit"),
    (re.compile(r"STAR|面试经历"), "record_star"),
]


@dataclass
class IntentResult:
    intent: str
    task_type: str
    agent_type: AgentType
    confidence: float
    method: str  # "rule" | "llm" | "default"
    # v0.8: secondary intents produced by the LLM classifier; feed
    # :meth:`dispatch_parallel` when non-empty.
    secondary: list[str] = field(default_factory=list)


@dataclass
class DispatchResult:
    """Aggregate result from :meth:`MasterAgent.dispatch_parallel`."""

    primary: AgentResult
    extras: dict[str, AgentResult]  # task_type → result

    @property
    def content(self) -> str:
        return self.primary.content


class MasterAgent:
    def __init__(self, llm: LLMGateway | None = None) -> None:
        self._llm = llm
        self._agents: dict[AgentType, BaseAgent] = {}

    # ---------- registration / routing ----------

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_type] = agent

    def route(self, context) -> BaseAgent:  # noqa: ANN001 - AgentContext, kept loose for compat
        """Sync route by explicit task_type (used by the streaming path)."""
        agent_type = self._agent_for_task(context.task_type)
        agent = self._agents.get(agent_type)
        if agent is None:
            # Fall back to any efficiency agent (the only streaming one).
            agent = self._agents.get(AgentType.EFFICIENCY)
        if agent is None:
            raise LookupError(f"No agent registered for task_type {context.task_type!r}")
        return agent

    @staticmethod
    def _agent_for_task(task_type: str) -> AgentType:
        if task_type in EFFICIENCY_TASKS:
            return AgentType.EFFICIENCY
        if task_type in RESUME_TASKS:
            return AgentType.RESUME
        if task_type in ANALYSIS_TASKS:
            return AgentType.ANALYSIS
        if task_type in JOB_TASKS:
            return AgentType.JOB
        return AgentType.EFFICIENCY

    # ---------- intent classification ----------

    def classify_rule(self, text: str) -> IntentResult | None:
        for pattern, intent in _RULES:
            if pattern.search(text):
                task_type, agent_type = _INTENT_TABLE[intent]
                return IntentResult(intent, task_type, agent_type, 0.9, "rule")
        return None

    async def classify(self, text: str) -> IntentResult:
        """Two-stage classification: rule → Haiku fallback → default."""
        hit = self.classify_rule(text)
        if hit is not None:
            return hit

        if self._llm is not None:
            try:
                result = await self._classify_llm(text)
                if result is not None:
                    return result
            except Exception as e:  # noqa: BLE001
                logger.warning("intent_llm_fallback_failed", error=str(e))

        # Default: safest general-purpose chain.
        task_type, agent_type = _INTENT_TABLE["free_format"]
        return IntentResult("free_format", task_type, agent_type, 0.3, "default")

    async def _classify_llm(self, text: str) -> IntentResult | None:
        from app.agents.prompt_loader import load_prompt
        from app.config import get_settings

        prompt = load_prompt("intent_classify")
        raw, _ = await self._llm.generate(  # type: ignore[union-attr]
            system_prompt=prompt.system,
            user_message=prompt.render(input_content=text[:2000]),
            config=LLMConfig(model=get_settings().llm_intent_model, temperature=0.0, max_tokens=128),
            cache_system_prompt=True,
        )
        data = parse_json_object(raw)
        intent = str(data.get("intent", "")).strip()
        if intent not in _INTENT_TABLE:
            return None
        task_type, agent_type = _INTENT_TABLE[intent]
        conf = data.get("confidence", 0.6)
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.6
        raw_secondary = data.get("secondary") or []
        secondary: list[str] = []
        if isinstance(raw_secondary, list):
            for name in raw_secondary:
                name = str(name).strip()
                if name and name != intent and name in _INTENT_TABLE:
                    secondary.append(name)
        return IntentResult(
            intent, task_type, agent_type, round(conf, 2), "llm", secondary=secondary
        )

    # ---------- v0.8 parallel dispatch ----------

    async def dispatch_parallel(
        self, context: AgentContext, *, extras_task_types: list[str]
    ) -> DispatchResult:
        """Run the primary agent + secondary agents concurrently.

        Guarded by ``MASTER_PARALLEL_ENABLED``. Extras that fail are logged and
        omitted from the result — they should never affect the primary reply.
        """
        primary_task = asyncio.create_task(self._safe_execute(context))

        if not extras_task_types or not get_settings().master_parallel_enabled:
            primary = await primary_task
            return DispatchResult(primary=primary or _empty_result(), extras={})

        # Deduplicate and skip anything already covered by the primary path.
        seen: set[str] = {context.task_type}
        extra_contexts: list[tuple[str, AgentContext]] = []
        for tt in extras_task_types:
            if tt in seen:
                continue
            seen.add(tt)
            extra_contexts.append(
                (
                    tt,
                    AgentContext(
                        user_id=context.user_id,
                        task_type=tt,
                        input_content=context.input_content,
                        profile_summary=context.profile_summary,
                        conversation_history=context.conversation_history,
                        metadata=dict(context.metadata),
                    ),
                )
            )

        extra_tasks = {
            tt: asyncio.create_task(self._safe_execute(ctx))
            for tt, ctx in extra_contexts
        }

        primary = await primary_task
        extras: dict[str, AgentResult] = {}
        for tt, task in extra_tasks.items():
            result = await task
            if result is not None:
                extras[tt] = result
        logger.info(
            "master_parallel_dispatch_done",
            primary=context.task_type,
            extras=list(extras.keys()),
            failed=[tt for tt, task in extra_tasks.items() if task.result() is None],
        )
        return DispatchResult(primary=primary or _empty_result(), extras=extras)

    async def _safe_execute(self, context: AgentContext) -> AgentResult | None:
        try:
            agent = self._agents.get(self._agent_for_task(context.task_type))
            if agent is None:
                return None
            return await agent.execute(context)
        except NotImplementedError:
            # Some agents (Resume) are non-streaming and don't implement
            # execute() for every task_type. Silently skip.
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "master_dispatch_agent_failed",
                task_type=context.task_type,
                error=str(e),
            )
            return None


def _empty_result() -> AgentResult:
    return AgentResult(content="")
