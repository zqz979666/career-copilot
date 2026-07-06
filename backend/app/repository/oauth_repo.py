"""Repository for oauth_connections (v0.8)."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import OAuthConnection


class OAuthConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, provider: str) -> OAuthConnection | None:
        result = await self.session.execute(
            select(OAuthConnection).where(
                OAuthConnection.user_id == user_id,
                OAuthConnection.provider == provider,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_provider_user(
        self, provider: str, provider_user_id: str
    ) -> OAuthConnection | None:
        result = await self.session.execute(
            select(OAuthConnection).where(
                OAuthConnection.provider == provider,
                OAuthConnection.provider_user_id == provider_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[OAuthConnection]:
        result = await self.session.execute(
            select(OAuthConnection).where(OAuthConnection.user_id == user_id)
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        user_id: UUID,
        provider: str,
        provider_user_id: str | None,
        provider_login: str | None,
        scopes: str | None,
        access_token_encrypted: str,
        refresh_token_encrypted: str | None,
        meta: dict | None = None,
    ) -> OAuthConnection:
        existing = await self.get(user_id, provider)
        if existing is None:
            conn = OAuthConnection(
                user_id=user_id,
                provider=provider,
                provider_user_id=provider_user_id,
                provider_login=provider_login,
                scopes=scopes,
                access_token_encrypted=access_token_encrypted,
                refresh_token_encrypted=refresh_token_encrypted,
                status="active",
                meta=meta or {},
            )
            self.session.add(conn)
            await self.session.commit()
            await self.session.refresh(conn)
            return conn
        existing.provider_user_id = provider_user_id
        existing.provider_login = provider_login
        existing.scopes = scopes
        existing.access_token_encrypted = access_token_encrypted
        if refresh_token_encrypted:
            existing.refresh_token_encrypted = refresh_token_encrypted
        existing.status = "active"
        if meta is not None:
            existing.meta = meta
        await self.session.commit()
        await self.session.refresh(existing)
        return existing

    async def delete(self, user_id: UUID, provider: str) -> bool:
        conn = await self.get(user_id, provider)
        if conn is None:
            return False
        await self.session.delete(conn)
        await self.session.commit()
        return True
