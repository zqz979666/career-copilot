"""Redis Streams helpers for v1.0 event-driven flows."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis

from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class StreamEvent:
    stream: str
    user_id: str | None
    payload: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_fields(self) -> dict[str, str]:
        body = {
            "event_id": self.event_id,
            "created_at": self.created_at,
            "user_id": self.user_id,
            "payload": self.payload,
        }
        return {"data": json.dumps(body, ensure_ascii=False, default=str)}


class EventPublisher:
    """Small wrapper around Redis XADD with bounded stream length."""

    def __init__(self, redis: Redis, *, maxlen: int = 100_000) -> None:
        self._redis = redis
        self._maxlen = maxlen

    async def publish(self, event: StreamEvent) -> str:
        try:
            message_id = await self._redis.xadd(
                event.stream,
                event.to_fields(),
                maxlen=self._maxlen,
                approximate=True,
            )
            logger.info(
                "stream_event_published",
                stream=event.stream,
                event_id=event.event_id,
                message_id=message_id,
            )
            return str(message_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "stream_event_publish_failed",
                stream=event.stream,
                event_id=event.event_id,
                error=str(e),
            )
            raise
