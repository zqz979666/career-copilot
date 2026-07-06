"""Unified Claude LLM gateway.

Responsibilities:
- Single entry point for all LLM calls (Rule #4 in the architecture red-lines).
- Prompt Cache (ephemeral) on system prompts — enabled from v0.1.
- Token accounting, cost tracking, timeout/retry, streaming/blocking modes.
- Small in-process aggregates (call count, cost) — real observability lands in v1.0.

Model pricing (USD per 1M tokens, Claude Sonnet 4.x class):
    input:              $3.00
    output:             $15.00
    cache read:         $0.30
    cache creation:     $3.75
"""
from __future__ import annotations

import base64
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from anthropic import APIError, AsyncAnthropic

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class LLMConfig:
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    timeout: float | None = None


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": round(self.latency_ms, 2),
            "model": self.model,
        }


# ---------- Pricing table (USD per 1M tokens) ----------
_PRICING: dict[str, dict[str, float]] = {
    # Claude Sonnet 4.x family
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    # Haiku (used for intent routing from v0.5)
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_write": 1.25},
    # Opus (heavy work; used sparingly)
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_read": 1.5, "cache_write": 18.75},
}

_DEFAULT_PRICING = _PRICING["claude-sonnet-4-5"]


def _pricing_for(model: str) -> dict[str, float]:
    # Best-effort prefix match: `claude-sonnet-4-5-20260101` → sonnet-4-5 pricing.
    for key, price in _PRICING.items():
        if model.startswith(key):
            return price
    return _DEFAULT_PRICING


class LLMGateway:
    """Unified LLM gateway.

    v0.1 scope: Claude Sonnet (blocking + streaming), Prompt Cache on system prompt,
    in-process cost aggregation. Configuration is driven by :class:`app.config.Settings`
    and per-call overrides via :class:`LLMConfig`.
    """

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = AsyncAnthropic(
            api_key=api_key or settings.anthropic_api_key or None,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )
        self._call_count = 0
        self._total_cost_usd = 0.0

    # -------- public --------

    @property
    def call_count(self) -> int:
        return self._call_count

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        config: LLMConfig | None = None,
        cache_system_prompt: bool = True,
    ) -> tuple[str, LLMUsage]:
        """Blocking generation. Returns (text, usage)."""
        model, max_tokens, temperature = self._resolve(config)
        start = time.time()

        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=self._build_system(system_prompt, cache_system_prompt),
                messages=[{"role": "user", "content": user_message}],
            )
        except APIError as e:
            logger.error("llm_api_error", error=str(e), model=model)
            raise

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = self._compute_usage(response.usage, time.time() - start, model)
        self._track(usage)
        logger.info("llm_generate_ok", **usage.to_dict())
        return text, usage

    async def generate_vision(
        self,
        system_prompt: str,
        user_message: str,
        image_bytes: bytes,
        media_type: str = "image/png",
        config: LLMConfig | None = None,
        cache_system_prompt: bool = True,
    ) -> tuple[str, LLMUsage]:
        """Blocking multimodal generation (image + text). Returns (text, usage).

        Used for screenshot OCR / structuring (v0.5 EfficiencyAgent
        screenshot_parse). The image is sent base64-encoded alongside the text
        instruction.
        """
        model, max_tokens, temperature = self._resolve(config)
        start = time.time()
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        content = [
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            },
            {"type": "text", "text": user_message},
        ]

        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=self._build_system(system_prompt, cache_system_prompt),
                messages=[{"role": "user", "content": content}],
            )
        except APIError as e:
            logger.error("llm_vision_api_error", error=str(e), model=model)
            raise

        text = "".join(block.text for block in response.content if block.type == "text")
        usage = self._compute_usage(response.usage, time.time() - start, model)
        self._track(usage)
        logger.info("llm_vision_ok", **usage.to_dict())
        return text, usage

    async def stream(
        self,
        system_prompt: str,
        user_message: str,
        config: LLMConfig | None = None,
        cache_system_prompt: bool = True,
    ) -> AsyncGenerator[str, None]:
        """Streaming generation. Yields text chunks.

        Usage is accounted after the stream closes; retrieve it via the
        ``last_usage`` attribute on the returned async generator's parent gateway
        (or use :meth:`stream_with_usage` for a tuple return).
        """
        model, max_tokens, temperature = self._resolve(config)
        start = time.time()

        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=self._build_system(system_prompt, cache_system_prompt),
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            async for text in stream.text_stream:
                yield text

            final = await stream.get_final_message()
            usage = self._compute_usage(final.usage, time.time() - start, model)
            self._track(usage)
            self._last_usage = usage
            logger.info("llm_stream_ok", **usage.to_dict())

    async def stream_with_usage(
        self,
        system_prompt: str,
        user_message: str,
        config: LLMConfig | None = None,
        cache_system_prompt: bool = True,
    ) -> AsyncGenerator[tuple[str | None, LLMUsage | None], None]:
        """Streaming that also yields a final `(None, usage)` tuple after completion.

        Chunks are yielded as ``(text, None)`` and the final entry is
        ``(None, usage)`` — makes it easy for callers to persist usage after
        exhausting the stream.
        """
        model, max_tokens, temperature = self._resolve(config)
        start = time.time()

        async with self._client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=self._build_system(system_prompt, cache_system_prompt),
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            async for text in stream.text_stream:
                yield text, None

            final = await stream.get_final_message()
            usage = self._compute_usage(final.usage, time.time() - start, model)
            self._track(usage)
            yield None, usage

    # -------- internals --------

    def _resolve(self, config: LLMConfig | None) -> tuple[str, int, float]:
        s = self._settings
        cfg = config or LLMConfig()
        return (
            cfg.model or s.llm_default_model,
            cfg.max_tokens or s.llm_max_tokens,
            cfg.temperature if cfg.temperature is not None else s.llm_temperature,
        )

    @staticmethod
    def _build_system(prompt: str, cache: bool) -> list[dict[str, Any]]:
        block: dict[str, Any] = {"type": "text", "text": prompt}
        if cache:
            block["cache_control"] = {"type": "ephemeral"}
        return [block]

    @staticmethod
    def _compute_usage(usage_obj: Any, elapsed_s: float, model: str) -> LLMUsage:
        input_tokens = getattr(usage_obj, "input_tokens", 0) or 0
        output_tokens = getattr(usage_obj, "output_tokens", 0) or 0
        cache_read = getattr(usage_obj, "cache_read_input_tokens", 0) or 0
        cache_create = getattr(usage_obj, "cache_creation_input_tokens", 0) or 0

        price = _pricing_for(model)
        cost = (
            input_tokens * price["input"] / 1_000_000
            + output_tokens * price["output"] / 1_000_000
            + cache_read * price["cache_read"] / 1_000_000
            + cache_create * price["cache_write"] / 1_000_000
        )
        return LLMUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            cost_usd=cost,
            latency_ms=elapsed_s * 1000,
            model=model,
        )

    def _track(self, usage: LLMUsage) -> None:
        self._call_count += 1
        self._total_cost_usd += usage.cost_usd
