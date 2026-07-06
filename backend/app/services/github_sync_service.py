"""GitHub Sync Service (v0.8) — 3rd-party ingest pipeline.

Flow:

    OAuth callback            manual pull            webhook
          │                        │                    │
          ▼                        ▼                    ▼
    ┌─────────────────────────────────────────────────────┐
    │                GitHubSyncService                    │
    │  · verifies user link                               │
    │  · fetches minimal PR shape from adapter            │
    │  · Data Minimizer applied (no diff, no reviews)     │
    │  · records SyncEvent row (idempotent)               │
    │  · funnels candidates to ProfileEngine              │
    └─────────────────────────────────────────────────────┘

Idempotency: the ``(provider, external_id)`` UNIQUE index on ``sync_events``
plus ``profile_entries.source_ref`` guarantee that replaying the same webhook
delivery / manual sync is a no-op.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.github import (
    GitHubClient,
    GitHubError,
    GitHubNotConfigured,
    GitHubPullRequest,
)
from app.config import get_settings
from app.logging_config import get_logger
from app.repository.oauth_repo import OAuthConnectionRepository
from app.repository.sync_event_repo import SyncEventRepository
from app.repository.user_repo import UserRepository
from app.security.crypto import TokenCryptoError, decrypt_token
from app.services import profile_merge as pm
from app.services.event_bus import EventPublisher, StreamEvent
from app.services.profile_engine import ProfileEngine

logger = get_logger(__name__)


class GitHubSyncError(RuntimeError):
    """Raised when a sync attempt fails in a caller-actionable way."""


@dataclass
class SyncResult:
    fetched: int
    created: int
    updated: int
    skipped_duplicates: int


class GitHubSyncService:
    """Thin orchestration layer that keeps I/O + persistence out of the client."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker,
        profile_engine: ProfileEngine,
    ) -> None:
        self._session_factory = session_factory
        self._profile_engine = profile_engine
        self._event_publisher: EventPublisher | None = None

    def set_event_publisher(self, publisher: EventPublisher) -> None:
        self._event_publisher = publisher

    # ---------- manual pull ----------

    async def sync_pull_requests(
        self, user_id: UUID, *, limit: int = 30
    ) -> SyncResult:
        """Pull the user's recent PRs and fold them into their Profile.

        Returns counts so the API layer can surface "n new / m updated" to the
        UI without loading the entire profile.
        """
        async with self._session_factory() as session:
            conn = await OAuthConnectionRepository(session).get(user_id, "github")
            if conn is None or conn.status != "active":
                raise GitHubSyncError("github_not_connected")
            if not conn.provider_login:
                raise GitHubSyncError("github_login_missing")
            try:
                token = decrypt_token(conn.access_token_encrypted)
            except TokenCryptoError as e:
                raise GitHubSyncError("github_token_unreadable") from e
            login = conn.provider_login

        try:
            async with GitHubClient() as client:
                prs = await client.list_user_pull_requests(
                    token, login=login, limit=limit
                )
        except GitHubNotConfigured as e:
            raise GitHubSyncError("github_not_configured") from e
        except GitHubError as e:
            raise GitHubSyncError(str(e)) from e

        created_total = 0
        updated_total = 0
        skipped = 0
        candidates: list[pm.Candidate] = []
        for pr in prs:
            payload = _pr_to_payload(pr)
            was_created = await self._record_event(
                user_id=user_id,
                event_type="pull_request",
                external_id=f"github:pr:{pr.node_id}",
                payload=payload,
            )
            if not was_created:
                skipped += 1
            candidates.extend(pm.github_pr_to_candidates(payload))

        if candidates:
            stats = await self._profile_engine.ingest_third_party(user_id, candidates)
            created_total = int(stats.get("created", 0))
            updated_total = int(stats.get("updated", 0))

        logger.info(
            "github_sync_done",
            user_id=str(user_id),
            fetched=len(prs),
            created=created_total,
            updated=updated_total,
            skipped=skipped,
        )
        return SyncResult(
            fetched=len(prs),
            created=created_total,
            updated=updated_total,
            skipped_duplicates=skipped,
        )

    # ---------- webhook ingest ----------

    async def ingest_webhook(
        self,
        *,
        event_type: str,
        minimal: dict[str, Any],
        delivery_id: str | None = None,
    ) -> dict[str, Any]:
        """Consume a validated webhook payload and update the Profile.

        Returns a small dict for the HTTP response. Never raises for "user not
        linked" — silent no-op is the safer behavior (we don't want GitHub to
        keep retrying because we happened to not know that user).
        """
        github_user_id = str(minimal.get("github_user_id") or "").strip()
        if not github_user_id:
            return {"status": "ignored", "reason": "missing_user_id"}

        async with self._session_factory() as session:
            user = await UserRepository(session).find_by_github_user_id(github_user_id)
        if user is None:
            return {"status": "user_not_linked", "github_user_id": github_user_id}

        external_id = _webhook_external_id(event_type, minimal, delivery_id)
        was_created = await self._record_event(
            user_id=user.id,
            event_type=event_type,
            external_id=external_id,
            payload=minimal,
        )
        if not was_created:
            return {"status": "duplicate", "external_id": external_id}

        mode = get_settings().sync_event_mode
        if mode in {"dual", "event"} and self._event_publisher is not None:
            try:
                await self._event_publisher.publish(
                    StreamEvent(
                        stream="events:sync.github",
                        user_id=str(user.id),
                        payload={
                            "event_type": event_type,
                            "external_id": external_id,
                            "minimal_payload": minimal,
                        },
                    )
                )
            except Exception as e:  # noqa: BLE001
                if mode == "event":
                    raise
                logger.warning("sync_event_publish_failed_fallback_direct", error=str(e))
        if mode == "event":
            await self._mark_event_processed(external_id)
            return {
                "status": "queued",
                "event": event_type,
                "user_id": str(user.id),
                "external_id": external_id,
            }

        if event_type == "pull_request":
            candidates = pm.github_pr_to_candidates(minimal)
        elif event_type == "push":
            candidates = pm.github_push_to_candidates(minimal)
        else:
            candidates = []

        stats: dict[str, int] = {}
        if candidates:
            stats = await self._profile_engine.ingest_third_party(user.id, candidates)

        # Mark the sync_event as processed so the ledger reflects success.
        await self._mark_event_processed(external_id)

        return {
            "status": "ok",
            "event": event_type,
            "user_id": str(user.id),
            "candidates": len(candidates),
            **stats,
        }

    # ---------- internals ----------

    async def _record_event(
        self,
        *,
        user_id: UUID | None,
        event_type: str,
        external_id: str,
        payload: dict[str, Any],
    ) -> bool:
        async with self._session_factory() as session:
            _, created = await SyncEventRepository(session).record(
                provider="github",
                event_type=event_type,
                external_id=external_id,
                payload=payload,
                user_id=user_id,
            )
            return created

    async def _mark_event_processed(self, external_id: str) -> None:
        """Best-effort ledger update — we already committed the profile write."""
        try:
            async with self._session_factory() as session:
                repo = SyncEventRepository(session)
                event = await repo.get_by_external_id("github", external_id)
                if event is not None:
                    await repo.mark_processed(event.id)
        except Exception as e:  # noqa: BLE001
            logger.warning("sync_event_mark_processed_failed", error=str(e))


def _pr_to_payload(pr: GitHubPullRequest) -> dict[str, Any]:
    """Convert an adapter PR dataclass into the minimal dict shape."""
    return {
        "event": "pull_request",
        "node_id": pr.node_id,
        "number": pr.number,
        "title": pr.title,
        "body": pr.body,
        "repo_full_name": pr.repo_full_name,
        "state": pr.state,
        "merged": pr.merged,
        "merged_at": pr.merged_at,
        "html_url": pr.html_url,
    }


def _webhook_external_id(
    event_type: str, minimal: dict[str, Any], delivery_id: str | None
) -> str:
    """Build the (provider, external_id) key used for sync-event idempotency.

    Uses the PR node_id where present (survives redeliveries); falls back to
    GitHub's ``X-GitHub-Delivery`` header otherwise.
    """
    node_id = (minimal.get("node_id") or "").strip()
    if event_type == "pull_request" and node_id:
        action = str(minimal.get("action") or "sync").lower()
        return f"github:pr:{node_id}:{action}"
    if delivery_id:
        return f"github:delivery:{delivery_id}"
    # Last resort — synthesise from repo + event kind. Not perfectly unique
    # but avoids UNIQUE-violation on the ledger.
    return f"github:{event_type}:{minimal.get('repo_full_name') or 'unknown'}"
