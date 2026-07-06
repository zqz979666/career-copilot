"""Tests for v1.0 calendar/jira webhook event publishing."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.webhooks import router
from app.dependencies import get_event_publisher


class _FakePublisher:
    def __init__(self) -> None:
        self.events: list = []

    async def publish(self, event):  # noqa: ANN001
        self.events.append(event)
        return "1-0"


def _client_with_publisher(pub: _FakePublisher) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_event_publisher] = lambda: pub
    return TestClient(app)


def test_calendar_webhook_publishes_minimal_event() -> None:
    pub = _FakePublisher()
    client = _client_with_publisher(pub)
    payload = {
        "user_id": "u-1",
        "event_id": "cal-1",
        "title": "架构评审会",
        "summary": "讨论 v1.0 上线",
        "attendees": ["a@example.com"],  # minimizer should ignore
    }

    resp = client.post("/api/v1/webhooks/calendar", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert len(pub.events) == 1
    ev = pub.events[0]
    assert ev.stream == "events:sync.calendar"
    assert ev.user_id == "u-1"
    assert ev.payload == {
        "event_id": "cal-1",
        "title": "架构评审会",
        "summary": "讨论 v1.0 上线",
    }


def test_jira_webhook_publishes_minimal_event() -> None:
    pub = _FakePublisher()
    client = _client_with_publisher(pub)
    payload = {
        "user_id": "u-2",
        "issue_key": "CC-123",
        "title": "修复同步延迟",
        "status": "Done",
        "comments": ["should be dropped"],
    }

    resp = client.post("/api/v1/webhooks/jira", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"
    assert len(pub.events) == 1
    ev = pub.events[0]
    assert ev.stream == "events:sync.jira"
    assert ev.user_id == "u-2"
    assert ev.payload == {
        "issue_key": "CC-123",
        "title": "修复同步延迟",
        "status": "Done",
    }
