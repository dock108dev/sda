from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.config import settings
from app.db import _get_engine
from app.dependencies.auth import verify_api_key
from app.logging_config import configure_logging
from app.middleware.logging import StructuredLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.realtime.manager import realtime_manager
from app.realtime.poller import db_poller
from app.realtime.sse import router as sse_router
from app.realtime.ws import router as ws_router
from app.analytics.api.analytics_routes import router as analytics_router
from app.routers import fairbet, reading_positions, social, sports
from app.routers.admin import odds_sync, pbp, pipeline, resolution, task_control, timeline_jobs

configure_logging(
    service="sports-data-admin-api",
    environment=settings.environment,
    log_level=settings.log_level,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop background tasks (DB poller for realtime events)."""
    db_poller.start()
    yield
    await db_poller.stop()


app = FastAPI(title="sports-data-admin", version="1.0.0", lifespan=lifespan)
logger = logging.getLogger(__name__)

app.add_middleware(StructuredLoggingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# All routers require API key authentication
auth_dependency = [Depends(verify_api_key)]

app.include_router(sports.router, dependencies=auth_dependency)
app.include_router(social.router, dependencies=auth_dependency)
app.include_router(reading_positions.router, dependencies=auth_dependency)
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
    odds_sync.router,
    prefix="/api/admin",
    tags=["admin", "odds"],
    dependencies=auth_dependency,
)
app.include_router(
    task_control.router,
    prefix="/api/admin",
    tags=["admin", "tasks"],
    dependencies=auth_dependency,
)
app.include_router(fairbet.router, dependencies=auth_dependency)
app.include_router(analytics_router, dependencies=auth_dependency)

# Realtime endpoints — WS uses its own auth (query param / header),
# SSE uses dependency-level auth. No router-level auth_dependency needed.
app.include_router(ws_router, tags=["realtime"])
app.include_router(sse_router, tags=["realtime"])


@app.get("/v1/realtime/status", dependencies=auth_dependency, tags=["realtime"])
async def realtime_status() -> JSONResponse:
    """Connected counts per channel and mode, plus poller debug info."""
    data = realtime_manager.status()
    data["poller"] = db_poller.stats()
    return JSONResponse(data)


@app.get("/healthz")
async def healthcheck() -> JSONResponse:
    components: dict[str, str] = {"app": "ok", "db": "ok"}

    try:
        async with _get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Healthcheck database connectivity failed.")
        components["db"] = "error"

    status = "ok" if components["db"] == "ok" else "unhealthy"
    payload: dict[str, str] = {"status": status, **components}
    if status != "ok":
        payload["error"] = "database unavailable"
        return JSONResponse(payload, status_code=503)
    return JSONResponse(payload)
