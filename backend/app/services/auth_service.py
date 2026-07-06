"""Auth service — password hashing, JWT issuance/verification."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings
from app.models.db import User
from app.repository.user_repo import UserRepository

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthError(Exception):
    """Raised on any authentication/authorization failure."""


class AuthService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._users = user_repo
        self._settings = get_settings()

    # ---------- password ----------

    @staticmethod
    def hash_password(password: str) -> str:
        return _pwd_context.hash(password)

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return _pwd_context.verify(plain, hashed)

    # ---------- registration / login ----------

    async def register(
        self, *, email: str, password: str, name: str | None = None
    ) -> User:
        if await self._users.get_by_email(email):
            raise AuthError("email_already_registered")
        return await self._users.create(
            email=email,
            password_hash=self.hash_password(password),
            name=name,
        )

    async def authenticate(self, *, email: str, password: str) -> User:
        user = await self._users.get_by_email(email)
        if user is None or not user.password_hash:
            raise AuthError("invalid_credentials")
        if not self.verify_password(password, user.password_hash):
            raise AuthError("invalid_credentials")
        return user

    # ---------- JWT ----------

    def issue_token(self, user_id: UUID) -> tuple[str, int]:
        settings = self._settings
        expire_delta = timedelta(minutes=settings.jwt_expire_minutes)
        expire_at = datetime.now(UTC) + expire_delta
        payload = {"sub": str(user_id), "exp": expire_at}
        token = jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
        return token, int(expire_delta.total_seconds())

    def decode_token(self, token: str) -> UUID:
        s = self._settings
        try:
            payload = jwt.decode(token, s.jwt_secret_key, algorithms=[s.jwt_algorithm])
            sub = payload.get("sub")
            if not sub:
                raise AuthError("missing_subject")
            return UUID(sub)
        except (JWTError, ValueError) as e:
            raise AuthError("invalid_token") from e
