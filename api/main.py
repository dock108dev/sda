from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.db import _get_engine
from app.dependencies.auth import verify_api_key
from app.logging_config import configure_logging
from app.metrics import unhandled_exceptions_total
from app.middleware.head_method import HeadAsGetMiddleware
from app.middleware.logging import StructuredLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.otel import configure_telemetry, instrument_fastapi
from app.routers import social, sports
from app.routers.admin import (
    circuit_breakers,
    coverage_report,
    pbp,
    pipeline,
    platform as admin_platform,
    quality_review,
    quality_summary,
    realtime as admin_realtime,
    resolution,
    task_control,
    timeline_jobs,
)
from app.routers.v1 import router as v1_router

configure_logging(
    service="sports-data-admin-api",
    environment=settings.environment,
    log_level=settings.log_level,
)

configure_telemetry(service_name="sports-data-admin-api", environment=settings.environment)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan hook for startup warnings."""
    if not settings.auth_enabled and settings.environment not in {"production", "staging"}:
        logging.getLogger("app.startup").warning(
            "AUTH_ENABLED=false — JWT role resolution treats callers as admin; "
            "intended for local development only (blocked in production/staging)."
        )
    yield


_is_prod = settings.environment in {"production", "staging"}

app = FastAPI(
    title="sports-data-admin",
    version="1.0.0",
    lifespan=lifespan,
    # Disable interactive docs in production to reduce attack surface.
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
    openapi_tags=[
        {
            "name": "v1",
            "description": "Consumer-safe sports game summary endpoints.",
        },
        {
            "name": "admin",
            "description": (
                "**Admin API** — Sports data and operational endpoints. "
                "Odds, analytics, simulator, and golf surfaces are intentionally disabled."
            ),
        },
    ],
)
logger = logging.getLogger(__name__)

instrument_fastapi(app)

app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)
# Outermost: rewrite HEAD requests to GET so probes exercise the same handler
# as GET requests. Body is dropped on the way out.
app.add_middleware(HeadAsGetMiddleware)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    unhandled_exceptions_total.inc()
    logger.exception(
        "unhandled_exception",
        extra={"path": request.url.path, "method": request.method},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ---------------------------------------------------------------------------
# Admin-internal API key dependency (used by admin UI routers)
# ---------------------------------------------------------------------------
auth_dependency = [Depends(verify_api_key)]

app.include_router(v1_router)
app.include_router(sports.router, dependencies=auth_dependency)
app.include_router(social.router, dependencies=auth_dependency)
app.include_router(
    admin_platform.router,
    prefix="/api/admin",
    tags=["admin", "platform"],
    dependencies=auth_dependency,
)
app.include_router(
    timeline_jobs.router,
    prefix="/api/admin/sports",
    tags=["admin"],
    dependencies=auth_dependency,
)
app.include_router(
    pipeline.router,
    prefix="/api/admin/sports",
    tags=["admin", "pipeline"],
    dependencies=auth_dependency,
)
app.include_router(
    pbp.router,
    prefix="/api/admin/sports",
    tags=["admin", "pbp"],
    dependencies=auth_dependency,
)
app.include_router(
    resolution.router,
    prefix="/api/admin/sports",
    tags=["admin", "resolution"],
    dependencies=auth_dependency,
)
app.include_router(
    task_control.router,
    prefix="/api/admin",
    tags=["admin", "tasks"],
    dependencies=auth_dependency,
)
app.include_router(
    circuit_breakers.router,
    prefix="/api/admin",
    tags=["admin", "circuit-breakers"],
    dependencies=auth_dependency,
)
app.include_router(
    coverage_report.router,
    prefix="/api/admin",
    tags=["admin", "pipeline"],
    dependencies=auth_dependency,
)
app.include_router(
    quality_summary.router,
    prefix="/api/admin",
    tags=["admin", "quality"],
    dependencies=auth_dependency,
)
app.include_router(
    quality_review.router,
    prefix="/api/admin",
    tags=["admin", "quality"],
    dependencies=auth_dependency,
)
app.include_router(
    admin_realtime.router,
    prefix="/api/admin",
    tags=["admin", "realtime"],
    dependencies=auth_dependency,
)


@app.get("/healthz")
async def healthcheck() -> JSONResponse:
    import redis.asyncio as aioredis

    components: dict[str, str] = {"app": "ok", "db": "ok", "redis": "ok"}

    try:
        async with _get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Healthcheck database connectivity failed.")
        components["db"] = "error"

    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
    except Exception:
        # Don't log.exception here — Redis being down is not a stack-trace
        # event during a healthcheck. Log at warning so it shows up in
        # ops dashboards without alarming.
        logger.warning("Healthcheck Redis connectivity failed.")
        components["redis"] = "error"

    db_ok = components["db"] == "ok"
    payload: dict[str, Any] = {
        "status": "ok" if db_ok else "unhealthy",
        **components,
    }
    if not db_ok:
        payload["error"] = "database unavailable"
        return JSONResponse(payload, status_code=503)
    return JSONResponse(payload)


@app.get("/health", include_in_schema=False)
async def health() -> JSONResponse:
    """Always-up liveness probe — no auth, no dependency checks."""
    return JSONResponse({"status": "ok"})


@app.get("/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    """Readiness probe — 200 when DB and Redis are reachable, 503 otherwise."""
    import redis.asyncio as aioredis

    result: dict[str, bool] = {"db": True, "redis": True}

    try:
        async with _get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Readiness check: DB unreachable")
        result["db"] = False

    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
    except Exception:
        logger.warning("Readiness check: Redis unreachable")
        result["redis"] = False

    if all(result.values()):
        return JSONResponse({"status": "ok", **result})
    return JSONResponse({"status": "unavailable", **result}, status_code=503)


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus metrics endpoint — text/plain exposition format."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
