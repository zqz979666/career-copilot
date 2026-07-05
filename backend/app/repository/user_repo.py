"""User repository."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self.session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        email: str,
        password_hash: str,
        name: str | None = None,
        auth_provider: str = "email",
    ) -> User:
        user = User(
            email=email,
            password_hash=password_hash,
            name=name,
            auth_provider=auth_provider,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update_memory_mode(self, user_id: UUID, memory_mode: str) -> User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.memory_mode = memory_mode
        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def get_memory_mode(self, user_id: UUID) -> str | None:
        """Cheap read of just the memory_mode column."""
        from sqlalchemy import select as _select

        result = await self.session.execute(
            _select(User.memory_mode).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
