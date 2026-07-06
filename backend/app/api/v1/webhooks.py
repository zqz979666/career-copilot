"""Webhook receivers (v0.8).

Currently only GitHub. All endpoints:

- verify the vendor's signature (HMAC-SHA256, constant-time),
- extract the Data Minimizer shape,
- delegate to :class:`GitHubSyncService.ingest_webhook` which handles
  ``sync_events`` idempotency + Profile Engine ingestion.

Never raises 500 for user-not-linked / unsupported-event: GitHub will retry
aggressively on non-2xx, and there's no point pushing that load on us for
events we intentionally ignore.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.dependencies import get_event_publisher, get_github_sync_service
from app.integrations.github import (
    extract_pr_minimal,
    extract_push_minimal,
    verify_webhook_signature,
)
from app.logging_config import get_logger
from app.models.schemas import WebhookAck
from app.services.event_bus import EventPublisher, StreamEvent
from app.services.github_sync_service import GitHubSyncService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/github", response_model=WebhookAck)
async def handle_github_webhook(
    request: Request,
    svc: GitHubSyncService = Depends(get_github_sync_service),
) -> WebhookAck:
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_signature")

    event_type = request.headers.get("X-GitHub-Event", "").strip()
    delivery_id = request.headers.get("X-GitHub-Delivery", "").strip() or None
    try:
        payload = await request.json()
    except Exception as e:  # noqa: BLE001
        logger.warning("github_webhook_bad_json", error=str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid_json") from e

    if event_type == "ping":
        return WebhookAck(status="pong")
    if event_type == "pull_request":
        minimal = extract_pr_minimal(payload)
    elif event_type == "push":
        minimal = extract_push_minimal(payload)
    else:
        return WebhookAck(status="ignored", detail={"event": event_type})

    result = await svc.ingest_webhook(
        event_type=event_type, minimal=minimal, delivery_id=delivery_id
    )
    logger.info(
        "github_webhook_processed",
        event=event_type,
        delivery=delivery_id,
        status=result.get("status"),
    )
    return WebhookAck(status=str(result.get("status") or "ok"), detail=result)


@router.post("/calendar", response_model=WebhookAck)
async def handle_calendar_webhook(
    request: Request,
    publisher: EventPublisher = Depends(get_event_publisher),
) -> WebhookAck:
    # v1.0 GA: webhook channel renew / poll worker handles full sync.
    payload = await request.json()
    await publisher.publish(
        StreamEvent(
            stream="events:sync.calendar",
            user_id=str(payload.get("user_id")) if payload.get("user_id") else None,
            payload={
                "event_id": payload.get("event_id"),
                "title": payload.get("title"),
                "summary": payload.get("summary"),
            },
        )
    )
    return WebhookAck(status="accepted", detail={"provider": "calendar"})


@router.post("/jira", response_model=WebhookAck)
async def handle_jira_webhook(
    request: Request,
    publisher: EventPublisher = Depends(get_event_publisher),
) -> WebhookAck:
    # v1.0 GA: webhook payload is minimized and consumed by sync workers.
    payload = await request.json()
    await publisher.publish(
        StreamEvent(
            stream="events:sync.jira",
            user_id=str(payload.get("user_id")) if payload.get("user_id") else None,
            payload={
                "issue_key": payload.get("issue_key"),
                "title": payload.get("title"),
                "status": payload.get("status"),
            },
        )
    )
    return WebhookAck(status="accepted", detail={"provider": "jira"})
