"""OAuth Service (v0.8) — handshake orchestration for 3rd-party providers.

Currently wires GitHub only. Keeps the crypto + repo access away from the
API layer so we can add Calendar / Jira in v1.0 with just another adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.integrations.github import GitHubClient, GitHubError, GitHubNotConfigured
from app.logging_config import get_logger
from app.repository.oauth_repo import OAuthConnectionRepository
from app.repository.user_repo import UserRepository
from app.security.crypto import encrypt_token

logger = get_logger(__name__)


class OAuthError(RuntimeError):
    """Raised when the OAuth handshake cannot complete."""


@dataclass
class OAuthConnectionOut:
    provider: str
    provider_user_id: str | None
    provider_login: str | None
    scopes: str | None
    status: str


class OAuthService:
    def __init__(self, *, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    # ---------- GitHub ----------

    def github_build_authorize_url(self, state: str) -> str:
        try:
            return GitHubClient.build_authorize_url(state)
        except GitHubNotConfigured as e:
            raise OAuthError("github_not_configured") from e

    async def github_complete(self, user_id: UUID, code: str) -> OAuthConnectionOut:
        """Exchange the code, fetch the user profile, upsert the connection."""
        try:
            async with GitHubClient() as client:
                token = await client.exchange_code(code)
                gh_user = await client.get_user(token.access_token)
        except GitHubNotConfigured as e:
            raise OAuthError("github_not_configured") from e
        except GitHubError as e:
            raise OAuthError(str(e)) from e

        async with self._session_factory() as session:
            user_repo = UserRepository(session)
            oauth_repo = OAuthConnectionRepository(session)

            # Guard against cross-user GitHub reuse. If another Career Copilot
            # account has already linked this GitHub identity, refuse.
            collision = await user_repo.find_by_github_user_id(gh_user.id)
            if collision is not None and collision.id != user_id:
                raise OAuthError("github_already_linked_to_other_user")

            await user_repo.link_github(
                user_id,
                github_user_id=gh_user.id,
                github_login=gh_user.login,
            )
            conn = await oauth_repo.upsert(
                user_id=user_id,
                provider="github",
                provider_user_id=gh_user.id,
                provider_login=gh_user.login,
                scopes=token.scope,
                access_token_encrypted=encrypt_token(token.access_token),
                refresh_token_encrypted=None,
                meta={"name": gh_user.name, "email": gh_user.email},
            )

        logger.info(
            "github_oauth_linked",
            user_id=str(user_id),
            login=gh_user.login,
            scopes=token.scope,
        )
        return OAuthConnectionOut(
            provider=conn.provider,
            provider_user_id=conn.provider_user_id,
            provider_login=conn.provider_login,
            scopes=conn.scopes,
            status=conn.status,
        )

    async def list_connections(self, user_id: UUID) -> list[OAuthConnectionOut]:
        async with self._session_factory() as session:
            rows = await OAuthConnectionRepository(session).list_for_user(user_id)
        return [
            OAuthConnectionOut(
                provider=r.provider,
                provider_user_id=r.provider_user_id,
                provider_login=r.provider_login,
                scopes=r.scopes,
                status=r.status,
            )
            for r in rows
        ]

    # ---------- Calendar / Jira (v1.0 lightweight handshake) ----------

    def calendar_build_authorize_url(self, state: str) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?response_type=code&client_id=dummy&scope=calendar.events.readonly&state={state}"
        )

    def jira_build_authorize_url(self, state: str) -> str:
        return (
            "https://auth.atlassian.com/authorize"
            f"?audience=api.atlassian.com&response_type=code&state={state}"
        )

    async def generic_complete(
        self, *, user_id: UUID, provider: str, code: str
    ) -> OAuthConnectionOut:
        if provider not in {"calendar", "jira"}:
            raise OAuthError("unsupported_provider")
        async with self._session_factory() as session:
            conn = await OAuthConnectionRepository(session).upsert(
                user_id=user_id,
                provider=provider,
                provider_user_id=f"{provider}:{user_id}",
                provider_login=f"{provider}_linked",
                scopes="readonly",
                access_token_encrypted=encrypt_token(code),
                refresh_token_encrypted=None,
                meta={"stub": True},
            )
        return OAuthConnectionOut(
            provider=conn.provider,
            provider_user_id=conn.provider_user_id,
            provider_login=conn.provider_login,
            scopes=conn.scopes,
            status=conn.status,
        )

    async def disconnect(self, user_id: UUID, provider: str) -> bool:
        async with self._session_factory() as session:
            oauth_repo = OAuthConnectionRepository(session)
            deleted = await oauth_repo.delete(user_id, provider)
            if provider == "github":
                await UserRepository(session).unlink_github(user_id)
        logger.info(
            "oauth_disconnected",
            user_id=str(user_id),
            provider=provider,
            deleted=deleted,
        )
        return deleted

    def to_dict(self, conn: OAuthConnectionOut) -> dict[str, Any]:
        return {
            "provider": conn.provider,
            "provider_user_id": conn.provider_user_id,
            "provider_login": conn.provider_login,
            "scopes": conn.scopes,
            "status": conn.status,
        }
