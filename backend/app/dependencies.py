"""FastAPI dependency-injection wiring.

Singletons (LLM Gateway, Agent Router, EfficiencyAgent, GenerateService) are
constructed once at startup and stored on `app.state`. Request-scoped
dependencies (DB session, current user) are functions.
"""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import AgentRouter, EfficiencyAgent
from app.api.middleware.rate_limit import RateLimiter
from app.config import get_settings
from app.db import AsyncSessionLocal, get_db_session
from app.llm import LLMGateway
from app.repository.user_repo import UserRepository
from app.services.auth_service import AuthError, AuthService
from app.services.extraction_service import ExtractionService
from app.services.generate_service import GenerateService
from app.services.resume_service import ResumeService
from app.services.speech_service import WhisperService


# ---------- Singleton factories (called from lifespan) ----------


def build_llm_gateway() -> LLMGateway:
    return LLMGateway()


def build_agent_router(llm: LLMGateway) -> AgentRouter:
    router = AgentRouter()
    router.register(EfficiencyAgent(llm=llm))
    return router


def build_extraction_service(llm: LLMGateway) -> ExtractionService:
    return ExtractionService(llm=llm, session_factory=AsyncSessionLocal)


def build_generate_service(
    router: AgentRouter, extraction: ExtractionService
) -> GenerateService:
    return GenerateService(
        router=router,
        session_factory=AsyncSessionLocal,
        extraction=extraction,
    )


def build_speech_service() -> WhisperService:
    return WhisperService()


def build_resume_service(llm: LLMGateway) -> ResumeService:
    return ResumeService(llm=llm)


def build_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def build_rate_limiter(redis: Redis) -> RateLimiter:
    return RateLimiter(redis=redis)


# ---------- Request-scoped dependencies ----------


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_generate_service(request: Request) -> GenerateService:
    svc: GenerateService | None = getattr(request.app.state, "generate_service", None)
    if svc is None:
        raise RuntimeError("GenerateService not initialized")
    return svc


def get_speech_service(request: Request) -> WhisperService:
    svc: WhisperService | None = getattr(request.app.state, "speech_service", None)
    if svc is None:
        raise RuntimeError("WhisperService not initialized")
    return svc


def get_resume_service(request: Request) -> ResumeService:
    svc: ResumeService | None = getattr(request.app.state, "resume_service", None)
    if svc is None:
        raise RuntimeError("ResumeService not initialized")
    return svc


def get_auth_service(session: DbSession) -> AuthService:
    return AuthService(UserRepository(session))


_bearer = HTTPBearer(auto_error=False)


async def get_current_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> UUID:
    """Require a valid JWT. Raises 401 otherwise."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing_authorization")
    try:
        return auth.decode_token(creds.credentials)
    except AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e


async def get_optional_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    auth: AuthService = Depends(get_auth_service),
) -> UUID | None:
    """Optional auth — used by generate endpoint for Level 0 anonymous flow."""
    if creds is None:
        return None
    try:
        return auth.decode_token(creds.credentials)
    except AuthError:
        return None
