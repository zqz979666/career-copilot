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

from app.agents import AnalysisAgent, EfficiencyAgent, JobAgent, MasterAgent, ResumeAgent
from app.api.middleware.rate_limit import RateLimiter
from app.config import get_settings
from app.db import AsyncSessionLocal, get_db_session
from app.llm import EmbeddingService, LLMGateway
from app.repository.user_repo import UserRepository
from app.services.auth_service import AuthError, AuthService
from app.services.analysis_service import AnalysisService
from app.services.document_service import DocumentService
from app.services.event_bus import EventPublisher
from app.services.extraction_service import ExtractionService
from app.services.generate_service import GenerateService
from app.services.github_sync_service import GitHubSyncService
from app.services.jd_service import JDService
from app.services.job_service import JobService
from app.services.oauth_service import OAuthService
from app.services.profile_engine import ProfileEngine
from app.services.report_service import ReportService
from app.services.resume_service import ResumeService
from app.services.resume_studio_service import ResumeStudioService
from app.services.screenshot_service import ScreenshotService
from app.services.speech_service import WhisperService
from app.services.trust_service import TrustService

# ---------- Singleton factories (called from lifespan) ----------


def build_llm_gateway() -> LLMGateway:
    return LLMGateway()


def build_embedding_service() -> EmbeddingService:
    return EmbeddingService()


def build_profile_engine(embeddings: EmbeddingService) -> ProfileEngine:
    return ProfileEngine(session_factory=AsyncSessionLocal, embeddings=embeddings)


def build_master_agent(llm: LLMGateway) -> MasterAgent:
    master = MasterAgent(llm=llm)
    master.register(EfficiencyAgent(llm=llm))
    master.register(ResumeAgent(llm=llm))
    if get_settings().analysis_agent_enabled:
        master.register(AnalysisAgent(llm=llm))
    if get_settings().job_agent_enabled:
        master.register(JobAgent(llm=llm))
    return master


def build_resume_agent(llm: LLMGateway) -> ResumeAgent:
    return ResumeAgent(llm=llm)


def build_analysis_agent(llm: LLMGateway) -> AnalysisAgent:
    return AnalysisAgent(llm=llm)


def build_job_agent(llm: LLMGateway) -> JobAgent:
    return JobAgent(llm=llm)


def build_extraction_service(llm: LLMGateway) -> ExtractionService:
    return ExtractionService(llm=llm, session_factory=AsyncSessionLocal)


def build_generate_service(
    router: MasterAgent,
    extraction: ExtractionService,
    profile_engine: ProfileEngine,
) -> GenerateService:
    return GenerateService(
        router=router,
        session_factory=AsyncSessionLocal,
        extraction=extraction,
        profile_engine=profile_engine,
    )


def build_jd_service(
    resume_agent: ResumeAgent, profile_engine: ProfileEngine
) -> JDService:
    return JDService(
        resume_agent=resume_agent,
        profile_engine=profile_engine,
        session_factory=AsyncSessionLocal,
    )


def build_resume_studio_service(
    resume_agent: ResumeAgent,
    profile_engine: ProfileEngine,
    jd_service: JDService,
) -> ResumeStudioService:
    return ResumeStudioService(
        resume_agent=resume_agent,
        profile_engine=profile_engine,
        jd_service=jd_service,
        session_factory=AsyncSessionLocal,
    )


def build_screenshot_service(llm: LLMGateway) -> ScreenshotService:
    return ScreenshotService(llm=llm)


def build_speech_service() -> WhisperService:
    return WhisperService()


def build_resume_service(llm: LLMGateway) -> ResumeService:
    return ResumeService(llm=llm)


def build_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def build_rate_limiter(redis: Redis) -> RateLimiter:
    return RateLimiter(redis=redis)


# ---------- v0.8 3rd-party integrations ----------


def build_oauth_service() -> OAuthService:
    return OAuthService(session_factory=AsyncSessionLocal)


def build_github_sync_service(profile_engine: ProfileEngine) -> GitHubSyncService:
    return GitHubSyncService(
        session_factory=AsyncSessionLocal, profile_engine=profile_engine
    )


def build_event_publisher(redis: Redis) -> EventPublisher:
    return EventPublisher(redis)


def build_analysis_service(
    analysis_agent: AnalysisAgent,
    profile_engine: ProfileEngine,
    event_publisher: EventPublisher | None = None,
) -> AnalysisService:
    return AnalysisService(
        analysis_agent=analysis_agent,
        profile_engine=profile_engine,
        session_factory=AsyncSessionLocal,
        event_publisher=event_publisher,
    )


def build_job_service(
    job_agent: JobAgent,
    profile_engine: ProfileEngine,
    event_publisher: EventPublisher | None = None,
) -> JobService:
    return JobService(
        job_agent=job_agent,
        profile_engine=profile_engine,
        session_factory=AsyncSessionLocal,
        event_publisher=event_publisher,
    )


def build_document_service(llm: LLMGateway, profile_engine: ProfileEngine) -> DocumentService:
    return DocumentService(
        llm=llm,
        profile_engine=profile_engine,
        session_factory=AsyncSessionLocal,
    )


def build_report_service(llm: LLMGateway) -> ReportService:
    return ReportService(llm=llm, session_factory=AsyncSessionLocal)


def build_trust_service() -> TrustService:
    return TrustService(session_factory=AsyncSessionLocal)


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


def get_profile_engine(request: Request) -> ProfileEngine:
    svc: ProfileEngine | None = getattr(request.app.state, "profile_engine", None)
    if svc is None:
        raise RuntimeError("ProfileEngine not initialized")
    return svc


def get_resume_studio_service(request: Request) -> ResumeStudioService:
    svc: ResumeStudioService | None = getattr(request.app.state, "resume_studio_service", None)
    if svc is None:
        raise RuntimeError("ResumeStudioService not initialized")
    return svc


def get_jd_service(request: Request) -> JDService:
    svc: JDService | None = getattr(request.app.state, "jd_service", None)
    if svc is None:
        raise RuntimeError("JDService not initialized")
    return svc


def get_screenshot_service(request: Request) -> ScreenshotService:
    svc: ScreenshotService | None = getattr(request.app.state, "screenshot_service", None)
    if svc is None:
        raise RuntimeError("ScreenshotService not initialized")
    return svc


def get_oauth_service(request: Request) -> OAuthService:
    svc: OAuthService | None = getattr(request.app.state, "oauth_service", None)
    if svc is None:
        raise RuntimeError("OAuthService not initialized")
    return svc


def get_github_sync_service(request: Request) -> GitHubSyncService:
    svc: GitHubSyncService | None = getattr(request.app.state, "github_sync_service", None)
    if svc is None:
        raise RuntimeError("GitHubSyncService not initialized")
    return svc


def get_event_publisher(request: Request) -> EventPublisher:
    svc: EventPublisher | None = getattr(request.app.state, "event_publisher", None)
    if svc is None:
        raise RuntimeError("EventPublisher not initialized")
    return svc


def get_analysis_service(request: Request) -> AnalysisService:
    svc: AnalysisService | None = getattr(request.app.state, "analysis_service", None)
    if svc is None:
        raise RuntimeError("AnalysisService not initialized")
    return svc


def get_job_service(request: Request) -> JobService:
    svc: JobService | None = getattr(request.app.state, "job_service", None)
    if svc is None:
        raise RuntimeError("JobService not initialized")
    return svc


def get_document_service(request: Request) -> DocumentService:
    svc: DocumentService | None = getattr(request.app.state, "document_service", None)
    if svc is None:
        raise RuntimeError("DocumentService not initialized")
    return svc


def get_report_service(request: Request) -> ReportService:
    svc: ReportService | None = getattr(request.app.state, "report_service", None)
    if svc is None:
        raise RuntimeError("ReportService not initialized")
    return svc


def get_trust_service(request: Request) -> TrustService:
    svc: TrustService | None = getattr(request.app.state, "trust_service", None)
    if svc is None:
        raise RuntimeError("TrustService not initialized")
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
