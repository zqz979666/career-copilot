"""Redis Streams consumer skeleton for v1.0."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis

from app.logging_config import get_logger

logger = get_logger(__name__)

Handler = Callable[[dict], Awaitable[None]]


class StreamConsumer:
    def __init__(self, redis: Redis, *, consumer_name: str = "consumer-1") -> None:
        self._redis = redis
        self._name = consumer_name
        self._stop = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()

    async def run(self, *, stream: str, group: str, handler: Handler) -> None:
        await self._ensure_group(stream=stream, group=group)
        while not self._stop.is_set():
            msgs = await self._redis.xreadgroup(
                groupname=group,
                consumername=self._name,
                streams={stream: ">"},
                count=32,
                block=5000,
            )
            for _, entries in msgs or []:
                for msg_id, fields in entries:
                    try:
                        payload = _decode_fields(fields)
                        await handler(payload)
                        await self._redis.xack(stream, group, msg_id)
                    except Exception as e:  # noqa: BLE001
                        logger.warning(
                            "stream_consumer_handle_failed",
                            stream=stream,
                            group=group,
                            message_id=msg_id,
                            error=str(e),
                        )

    async def _ensure_group(self, *, stream: str, group: str) -> None:
        try:
            await self._redis.xgroup_create(stream, group, id="$", mkstream=True)
        except Exception as e:  # noqa: BLE001
            if "BUSYGROUP" not in str(e):
                raise


def _decode_fields(fields: dict) -> dict:
    if "data" not in fields:
        return dict(fields)
    raw = fields.get("data")
    if not isinstance(raw, str):
        return dict(fields)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {"data": obj}
    except json.JSONDecodeError:
        return {"data": raw}
