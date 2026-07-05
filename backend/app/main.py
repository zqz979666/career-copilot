"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.middleware.rate_limit_headers import RateLimitHeadersMiddleware
from app.api.middleware.request_id import RequestIdMiddleware
from app.api.v1 import auth as auth_api
from app.api.v1 import generate as generate_api
from app.api.v1 import history as history_api
from app.api.v1 import meta as meta_api
from app.api.v1 import profile as profile_api
from app.api.v1 import settings as settings_api
from app.config import get_settings
from app.dependencies import (
    build_agent_router,
    build_extraction_service,
    build_generate_service,
    build_llm_gateway,
    build_rate_limiter,
    build_redis_client,
    build_resume_service,
    build_speech_service,
)
from app.logging_config import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger = get_logger("app.lifespan")
    settings = get_settings()

    # Wire up singletons (LLM Gateway → Agents → GenerateService).
    llm_gateway = build_llm_gateway()
    agent_router = build_agent_router(llm_gateway)
    extraction_service = build_extraction_service(llm_gateway)
    generate_service = build_generate_service(agent_router, extraction_service)
    speech_service = build_speech_service()
    resume_service = build_resume_service(llm_gateway)

    # Redis + Rate limiter (best-effort: don't block boot if Redis is unavailable).
    redis_client = build_redis_client()
    rate_limiter = None
    try:
        await redis_client.ping()
        rate_limiter = build_rate_limiter(redis_client)
        logger.info("redis_connected", url=settings.redis_url)
    except Exception as e:  # noqa: BLE001
        logger.warning("redis_unavailable_ratelimit_disabled", error=str(e))

    app.state.llm_gateway = llm_gateway
    app.state.agent_router = agent_router
    app.state.extraction_service = extraction_service
    app.state.generate_service = generate_service
    app.state.speech_service = speech_service
    app.state.resume_service = resume_service
    app.state.redis = redis_client
    app.state.rate_limiter = rate_limiter

    logger.info(
        "app_started",
        version=__version__,
        env=settings.app_env,
        llm_model=settings.llm_default_model,
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
    try:
        await redis_client.aclose()
    except Exception:  # noqa: BLE001
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Career Copilot API",
        version=__version__,
        description="v0.1 Alpha backend — 碎片输入 → AI 生成结构化工作成果",
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
    app.include_router(history_api.router)
    app.include_router(profile_api.router)
    app.include_router(settings_api.router)

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
