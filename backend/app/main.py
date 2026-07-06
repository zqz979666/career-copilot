"""FastAPI application entry point."""
from __future__ import annotations

import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.middleware.rate_limit_headers import RateLimitHeadersMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from app.api.v1 import auth as auth_api
from app.api.v1 import analysis as analysis_api
from app.api.v1 import documents as documents_api
from app.api.v1 import generate as generate_api
from app.api.v1 import history as history_api
from app.api.v1 import integrations as integrations_api
from app.api.v1 import jd as jd_api
from app.api.v1 import jobs as jobs_api
from app.api.v1 import meta as meta_api
from app.api.v1 import oauth as oauth_api
from app.api.v1 import profile as profile_api
from app.api.v1 import reports as reports_api
from app.api.v1 import resumes as resumes_api
from app.api.v1 import settings as settings_api
from app.api.v1 import trust as trust_api
from app.api.v1 import webhooks as webhooks_api
from app.config import get_settings
from app.dependencies import (
    build_analysis_agent,
    build_analysis_service,
    build_document_service,
    build_event_publisher,
    build_embedding_service,
    build_extraction_service,
    build_generate_service,
    build_github_sync_service,
    build_job_agent,
    build_job_service,
    build_jd_service,
    build_llm_gateway,
    build_master_agent,
    build_oauth_service,
    build_profile_engine,
    build_rate_limiter,
    build_redis_client,
    build_report_service,
    build_resume_agent,
    build_resume_service,
    build_resume_studio_service,
    build_screenshot_service,
    build_speech_service,
    build_trust_service,
)
from app.logging_config import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger("app.lifespan")
    settings = get_settings()

    # Wire up singletons.
    #   LLM Gateway + Embeddings
    #     → Profile Engine (data channel)
    #     → Master Agent (Efficiency + Resume) → Generate/Resume/JD services
    llm_gateway = build_llm_gateway()
    embedding_service = build_embedding_service()
    profile_engine = build_profile_engine(embedding_service)

    master_agent = build_master_agent(llm_gateway)
    resume_agent = build_resume_agent(llm_gateway)
    analysis_agent = build_analysis_agent(llm_gateway)
    job_agent = build_job_agent(llm_gateway)

    extraction_service = build_extraction_service(llm_gateway)
    generate_service = build_generate_service(
        master_agent, extraction_service, profile_engine
    )
    jd_service = build_jd_service(resume_agent, profile_engine)
    resume_studio_service = build_resume_studio_service(
        resume_agent, profile_engine, jd_service
    )
    screenshot_service = build_screenshot_service(llm_gateway)
    speech_service = build_speech_service()
    resume_service = build_resume_service(llm_gateway)

    # v0.8: OAuth + GitHub sync
    oauth_service = build_oauth_service()
    event_publisher = build_event_publisher(redis_client := build_redis_client())
    github_sync_service = build_github_sync_service(profile_engine)
    github_sync_service.set_event_publisher(event_publisher)
    analysis_service = build_analysis_service(
        analysis_agent, profile_engine, event_publisher
    )
    job_service = build_job_service(job_agent, profile_engine, event_publisher)
    document_service = build_document_service(llm_gateway, profile_engine)
    report_service = build_report_service(llm_gateway)
    trust_service = build_trust_service()

    # Redis + Rate limiter (best-effort: don't block boot if Redis is unavailable).
    rate_limiter = None
    try:
        await redis_client.ping()
        rate_limiter = build_rate_limiter(redis_client)
        logger.info("redis_connected", url=settings.redis_url)
    except Exception as e:  # noqa: BLE001
        logger.warning("redis_unavailable_ratelimit_disabled", error=str(e))

    app.state.llm_gateway = llm_gateway
    app.state.embedding_service = embedding_service
    app.state.profile_engine = profile_engine
    app.state.master_agent = master_agent
    app.state.resume_agent = resume_agent
    app.state.analysis_agent = analysis_agent
    app.state.job_agent = job_agent
    app.state.extraction_service = extraction_service
    app.state.generate_service = generate_service
    app.state.jd_service = jd_service
    app.state.resume_studio_service = resume_studio_service
    app.state.screenshot_service = screenshot_service
    app.state.speech_service = speech_service
    app.state.resume_service = resume_service
    app.state.oauth_service = oauth_service
    app.state.event_publisher = event_publisher
    app.state.github_sync_service = github_sync_service
    app.state.analysis_service = analysis_service
    app.state.job_service = job_service
    app.state.document_service = document_service
    app.state.report_service = report_service
    app.state.trust_service = trust_service
    app.state.redis = redis_client
    app.state.rate_limiter = rate_limiter

    logger.info(
        "app_started",
        version=__version__,
        env=settings.app_env,
        llm_model=settings.llm_default_model,
        intent_model=settings.llm_intent_model,
        embedding_enabled=embedding_service.enabled,
        has_llm_key=bool(settings.anthropic_api_key),
        has_whisper_key=bool(settings.openai_api_key),
        rate_limiter_enabled=rate_limiter is not None,
    )
    yield
    logger.info(
        "app_stopped",
        llm_calls=llm_gateway.call_count,
        llm_total_cost_usd=round(llm_gateway.total_cost_usd, 4),
    )
    with contextlib.suppress(Exception):
        await redis_client.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Career Copilot API",
        version=__version__,
        description=(
            "v1.0 GA backend — 4 Agent 架构（Efficiency/Resume/Analysis/Job）+ "
            "Redis Streams 事件总线 + 文档智能导入（PDF/DOCX）+ Calendar/Jira 扩展 "
            "+ Trust Ladder + 月度成长报告。"
        ),
        lifespan=lifespan,
    )

    # ----- middleware (order matters: outermost first) -----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
    )
    app.add_middleware(RateLimitHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # ----- routers -----
    app.include_router(meta_api.router)
    app.include_router(auth_api.router)
    app.include_router(generate_api.router)
    app.include_router(analysis_api.router)
    app.include_router(jobs_api.router)
    app.include_router(documents_api.router)
    app.include_router(reports_api.router)
    app.include_router(trust_api.router)
    app.include_router(history_api.router)
    app.include_router(profile_api.router)
    app.include_router(resumes_api.router)
    app.include_router(jd_api.router)
    app.include_router(settings_api.router)
    app.include_router(oauth_api.router)
    app.include_router(webhooks_api.router)
    app.include_router(integrations_api.router)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=(settings.app_env == "development"),
        log_level=settings.app_log_level.lower(),
    )
