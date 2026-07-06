"""Tests for Redis Streams publisher/consumer helpers (v1.0)."""
from __future__ import annotations

import asyncio
import json

from app.events.consumer import StreamConsumer, _decode_fields
from app.services.event_bus import EventPublisher, StreamEvent


class _FakeRedisPublisher:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def xadd(self, stream, fields, *, maxlen, approximate):  # noqa: ANN001
        self.calls.append(
            {
                "stream": stream,
                "fields": fields,
                "maxlen": maxlen,
                "approximate": approximate,
            }
        )
        return "1-0"


class _FakeRedisConsumer:
    def __init__(self, *, messages: list[tuple[str, dict]] | None = None) -> None:
        self._messages = messages or []
        self.group_created: list[tuple[str, str]] = []
        self.acks: list[tuple[str, str, str]] = []

    async def xgroup_create(self, stream, group, id="$", mkstream=True):  # noqa: ANN001
        self.group_created.append((stream, group))

    async def xreadgroup(self, **kwargs):  # noqa: ANN003
        stream = list(kwargs["streams"].keys())[0]
        if not self._messages:
            await asyncio.sleep(0.001)
            return []
        entries = [(mid, fields) for mid, fields in self._messages]
        self._messages = []
        return [(stream, entries)]

    async def xack(self, stream, group, msg_id):  # noqa: ANN001
        self.acks.append((stream, group, msg_id))


async def test_event_publisher_xadd_shape() -> None:
    redis = _FakeRedisPublisher()
    pub = EventPublisher(redis)  # type: ignore[arg-type]
    event = StreamEvent(
        stream="events:sync.github",
        user_id="u1",
        payload={"k": "v"},
        event_id="evt-1",
        created_at="2026-07-06T00:00:00+00:00",
    )
    message_id = await pub.publish(event)

    assert message_id == "1-0"
    assert len(redis.calls) == 1
    call = redis.calls[0]
    assert call["stream"] == "events:sync.github"
    assert call["maxlen"] == 100_000
    assert call["approximate"] is True
    decoded = json.loads(call["fields"]["data"])
    assert decoded["event_id"] == "evt-1"
    assert decoded["user_id"] == "u1"
    assert decoded["payload"] == {"k": "v"}


def test_decode_fields_fallbacks() -> None:
    assert _decode_fields({"x": "y"}) == {"x": "y"}
    assert _decode_fields({"data": 123}) == {"data": 123}
    assert _decode_fields({"data": "not-json"}) == {"data": "not-json"}
    assert _decode_fields({"data": '{"a":1}'}) == {"a": 1}


async def test_stream_consumer_reads_handler_and_acks() -> None:
    msg_fields = {"data": '{"event_id":"evt-1","payload":{"x":1}}'}
    redis = _FakeRedisConsumer(messages=[("1-0", msg_fields)])
    consumer = StreamConsumer(redis)  # type: ignore[arg-type]
    got: list[dict] = []

    async def _handler(payload: dict) -> None:
        got.append(payload)
        consumer.stop()

    await consumer.run(stream="events:test", group="g1", handler=_handler)
    assert redis.group_created == [("events:test", "g1")]
    assert got and got[0]["event_id"] == "evt-1"
    assert redis.acks == [("events:test", "g1", "1-0")]
