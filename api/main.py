from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from starlette.responses import JSONResponse, Response

from app.analytics.api.analytics_routes import router as analytics_router
from app.config import settings
from app.db import _get_engine, get_async_session
from app.otel import configure_telemetry, instrument_fastapi
from app.db.telemetry import CircuitBreakerTripEvent
from app.dependencies.auth import verify_api_key
from app.dependencies.roles import require_admin, require_user
from app.logging_config import configure_logging
from app.middleware.logging import StructuredLoggingMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.realtime.listener import pg_listener
from app.realtime.manager import realtime_manager
from app.realtime.poller import db_poller
from app.realtime.streams import RedisStreamsBridge
from app.realtime.sse import router as sse_router
from app.realtime.ws import router as ws_router
from app.routers import auth, fairbet, onboarding, preferences, simulator, social, sports
from app.routers.billing import router as billing_router
from app.routers.clubs import router as clubs_router
from app.routers.club_branding import router as club_branding_router
from app.routers.club_memberships import router as club_memberships_router
from app.routers.commerce import router as commerce_router
from app.routers.webhooks import router as webhooks_router
from app.routers.v1 import router as v1_router
from app.routers.model_odds import router as model_odds_router
from app.routers.golf import router as golf_router
from app.routers.admin import (
    audit as admin_audit,
    circuit_breakers,
    clubs as admin_clubs,
    coverage_report,
    odds_sync,
    pbp,
    pipeline,
    platform as admin_platform,
    quality_review,
    quality_summary,
    realtime as admin_realtime,
    resolution,
    task_control,
    timeline_jobs,
    users,
    webhooks as admin_webhooks,
)
from app.services.circuit_breaker_registry import registry as _cb_registry
from app.services.entitlement import EntitlementError, SeatLimitError, SubscriptionPastDueError
from app.services.pool_lifecycle import TransitionError

configure_logging(
    service="sports-data-admin-api",
    environment=settings.environment,
    log_level=settings.log_level,
)

configure_telemetry(service_name="sports-data-admin-api", environment=settings.environment)

_flush_logger = logging.getLogger(__name__ + ".cb_flush")


async def _circuit_breaker_flush_loop() -> None:
    """Drain pending circuit breaker trip events to DB every 10 seconds."""
    while True:
        await asyncio.sleep(10)
        events = _cb_registry.drain_pending()
        if not events:
            continue
        try:
            async with get_async_session() as session:
                for ev in events:
                    session.add(
                        CircuitBreakerTripEvent(
                            breaker_name=ev.breaker_name,
                            reason=ev.reason,
                            tripped_at=ev.tripped_at,
                        )
                    )
        except Exception:
            _flush_logger.warning(
                "circuit_breaker_flush_error",
                exc_info=True,
                extra={"pending_count": len(events)},
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks: streams bridge, LISTEN/NOTIFY listener, CB flush."""
    bridge = RedisStreamsBridge(settings.redis_url, realtime_manager.boot_epoch)
    realtime_manager.set_streams_bridge(bridge)
    await bridge.start(realtime_manager._dispatch_local)

    db_poller.start()
    pg_listener.start()
    flush_task = asyncio.create_task(_circuit_breaker_flush_loop())
    yield
    flush_task.cancel()
    await pg_listener.stop()
    await db_poller.stop()
    await bridge.stop()


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
            "description": (
                "**Consumer API v1** — Public read-only endpoints. "
                "Requires a valid ``X-API-Key`` header. Per-IP rate limiting applies. "
                "Response shapes are consumer-safe (pipeline internals omitted)."
            ),
        },
        {
            "name": "admin",
            "description": (
                "**Admin API** — Mutating and operational endpoints under "
                "``/api/admin/``. Admin role required. Never mixed with "
                "consumer ``/api/v1/`` routes (enforced by "
                "``scripts/lint_router_namespaces.py``)."
            ),
        },
        {
            "name": "auth",
            "description": (
                "**Authentication** — Sign up, log in, and retrieve "
                "the current user identity. Returns JWT tokens for "
                "use with ``Authorization: Bearer <token>``."
            ),
        },
        {
            "name": "simulator",
            "description": (
                "**MLB Game Simulator** — Run Monte Carlo simulations for any "
                "MLB matchup. Uses real Statcast data and trained ML models. "
                "Start with `GET /api/simulator/mlb/teams` to list available "
                "teams, then `POST /api/simulator/mlb` to run a simulation."
            ),
        },
        {
            "name": "golf",
            "description": (
                "**Golf** — PGA Tour tournament data powered by DataGolf. "
                "Tournaments, live leaderboards, player stats, outright odds, "
                "and DFS projections. All endpoints under `/api/golf`."
            ),
        },
        {
            "name": "golf-pools",
            "description": (
                "**Golf Pools** — Country club pick'em pools for PGA tournaments. "
                "Create pools, manage entries, and view live scored leaderboards. "
                "Endpoints under `/api/golf/pools`."
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
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)


@app.exception_handler(EntitlementError)
async def _entitlement_exception_handler(request: Request, exc: EntitlementError) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"code": "ENTITLEMENT_EXCEEDED", "detail": str(exc)},
    )


@app.exception_handler(SeatLimitError)
async def _seat_limit_exception_handler(request: Request, exc: SeatLimitError) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={"code": "SEAT_LIMIT_EXCEEDED", "detail": str(exc)},
    )


@app.exception_handler(SubscriptionPastDueError)
async def _subscription_past_due_handler(
    request: Request, exc: SubscriptionPastDueError
) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={"code": "SUBSCRIPTION_PAST_DUE", "detail": str(exc)},
    )


@app.exception_handler(TransitionError)
async def _transition_exception_handler(request: Request, exc: TransitionError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"code": "INVALID_TRANSITION", "detail": str(exc)},
    )


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
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

# ---------------------------------------------------------------------------
# Role-based dependencies for downstream consumer endpoints
# ---------------------------------------------------------------------------
user_dependency = [Depends(verify_api_key), Depends(require_user)]
admin_dependency = [Depends(verify_api_key), Depends(require_admin)]

# ---------------------------------------------------------------------------
# Consumer v1 API — read-only endpoints, per-IP rate limited.
# Auth (verify_consumer_api_key) is applied at the router level in v1/__init__.py.
# ---------------------------------------------------------------------------
app.include_router(v1_router)

# ---------------------------------------------------------------------------
# Auth — public (no API key needed for signup/login/me)
# ---------------------------------------------------------------------------
app.include_router(auth.router)
app.include_router(preferences.router)

# ---------------------------------------------------------------------------
# Public club lookup — no auth. Used by public club landing pages.
# ---------------------------------------------------------------------------
app.include_router(clubs_router)

# ---------------------------------------------------------------------------
# Club branding — PUT /api/v1/clubs/:id/branding (owner role, premium plan).
# ---------------------------------------------------------------------------
app.include_router(club_branding_router)

# ---------------------------------------------------------------------------
# Club membership — invite flow and RBAC (requires user JWT).
# ---------------------------------------------------------------------------
app.include_router(club_memberships_router)

# ---------------------------------------------------------------------------
# Onboarding — PUBLIC (no auth). Prospect-facing "claim your club" form.
# Rate-limited per-IP via RateLimitMiddleware's onboarding-strict tier.
# ---------------------------------------------------------------------------
app.include_router(onboarding.router)

# ---------------------------------------------------------------------------
# Stripe webhooks — NO auth (verified by Stripe-Signature header).
# Must be registered before Commerce so the raw body is readable.
# ---------------------------------------------------------------------------
app.include_router(webhooks_router)

# ---------------------------------------------------------------------------
# Commerce — API key required. Stripe checkout session creation.
# ---------------------------------------------------------------------------
app.include_router(commerce_router, dependencies=auth_dependency)

# ---------------------------------------------------------------------------
# Billing — JWT required (owner role). Stripe Customer Portal self-service.
# ---------------------------------------------------------------------------
app.include_router(billing_router, dependencies=auth_dependency)

# ---------------------------------------------------------------------------
# Public / Guest-accessible endpoints (API key required, no role gate)
# Games, sports data, reading positions, simulator — accessible to all roles
# ---------------------------------------------------------------------------
app.include_router(sports.router, dependencies=auth_dependency)
app.include_router(social.router, dependencies=auth_dependency)
app.include_router(simulator.router, dependencies=auth_dependency)

# ---------------------------------------------------------------------------
# FairBet — API key required, individual endpoints handle role-based
# filtering (pregame open to guest, full live for user+)
# ---------------------------------------------------------------------------
app.include_router(fairbet.router, dependencies=auth_dependency)
app.include_router(model_odds_router, dependencies=auth_dependency)

# ---------------------------------------------------------------------------
# Analytics — read-only endpoints (teams, profiles, rosters, predictions)
# are accessible to any API-key holder.  Mutation endpoints (train, delete,
# activate, batch jobs) require admin role via per-endpoint Depends.
# ---------------------------------------------------------------------------
app.include_router(analytics_router, dependencies=auth_dependency)

# ---------------------------------------------------------------------------
# Golf — tournament, player, odds, and DFS endpoints
# ---------------------------------------------------------------------------
app.include_router(golf_router, dependencies=auth_dependency)

# ---------------------------------------------------------------------------
# Admin UI routers — require admin role (Origin-based for admin UI,
# JWT-based for consumer apps)
# ---------------------------------------------------------------------------
# Admin SPA platform endpoints (/api/admin/stats, /api/admin/poll-health).
# Gated by the admin-tier API key only — not JWT/role — because the admin
# SPA reaches this backend through an nginx reverse proxy that injects the
# admin API key, and Caddy Basic Auth already scopes the SPA to operators.
app.include_router(
    admin_platform.router,
    prefix="/api/admin",
    tags=["admin", "platform"],
    dependencies=auth_dependency,
)
app.include_router(
    admin_clubs.router,
    prefix="/api/admin",
    tags=["admin", "provisioning"],
    dependencies=admin_dependency,
)
app.include_router(
    admin_audit.router,
    prefix="/api/admin",
    tags=["admin", "audit"],
    dependencies=admin_dependency,
)
app.include_router(
    admin_webhooks.router,
    prefix="/api/admin",
    tags=["admin", "webhooks"],
    dependencies=admin_dependency,
)

app.include_router(
    timeline_jobs.router,
    prefix="/api/admin/sports",
    tags=["admin"],
    dependencies=admin_dependency,
)
app.include_router(
    pipeline.router,
    prefix="/api/admin/sports",
    tags=["admin", "pipeline"],
    dependencies=admin_dependency,
)
app.include_router(
    pbp.router,
    prefix="/api/admin/sports",
    tags=["admin", "pbp"],
    dependencies=admin_dependency,
)
app.include_router(
    resolution.router,
    prefix="/api/admin/sports",
    tags=["admin", "resolution"],
    dependencies=admin_dependency,
)
app.include_router(
    odds_sync.router,
    prefix="/api/admin",
    tags=["admin", "odds"],
    dependencies=admin_dependency,
)
app.include_router(
    task_control.router,
    prefix="/api/admin",
    tags=["admin", "tasks"],
    dependencies=admin_dependency,
)
app.include_router(
    circuit_breakers.router,
    prefix="/api/admin",
    tags=["admin", "circuit-breakers"],
    dependencies=admin_dependency,
)
app.include_router(
    coverage_report.router,
    prefix="/api/admin",
    tags=["admin", "pipeline"],
    dependencies=admin_dependency,
)
app.include_router(
    quality_summary.router,
    prefix="/api/admin",
    tags=["admin", "quality"],
    dependencies=admin_dependency,
)
app.include_router(
    quality_review.router,
    prefix="/api/admin",
    tags=["admin", "quality"],
    dependencies=admin_dependency,
)
app.include_router(
    users.router,
    prefix="/api/admin",
    tags=["admin", "users"],
    dependencies=admin_dependency,
)
app.include_router(
    admin_realtime.router,
    prefix="/api/admin",
    tags=["admin", "realtime"],
    dependencies=admin_dependency,
)

# ---------------------------------------------------------------------------
# Realtime endpoints — WS uses its own auth (query param / header),
# SSE uses dependency-level auth. No router-level auth_dependency needed.
# ---------------------------------------------------------------------------
app.include_router(ws_router, tags=["realtime"])
app.include_router(sse_router, tags=["realtime"])


@app.get("/v1/realtime/status", dependencies=auth_dependency, tags=["realtime"])
async def realtime_status() -> JSONResponse:
    """Connected counts per channel and mode, plus listener debug info."""
    data = realtime_manager.status()
    data["poller"] = db_poller.stats()
    data["listener"] = pg_listener.stats()
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
    from app.db.golf_pools import GolfPool
    from app.db.stripe import WebhookDeliveryAttempt
    from app import metrics as _metrics

    try:
        async with get_async_session() as db:
            pool_count = await db.scalar(
                select(func.count()).select_from(GolfPool).where(
                    GolfPool.status.in_(["open", "locked", "live"])
                )
            )
            _metrics.active_pools_total.set(pool_count or 0)
    except Exception:
        logger.warning("metrics: failed to query active_pools_total")

    try:
        async with get_async_session() as db:
            depth = await db.scalar(
                select(func.count(WebhookDeliveryAttempt.event_id.distinct())).where(
                    WebhookDeliveryAttempt.outcome == "fail",
                    WebhookDeliveryAttempt.is_dead_letter.is_(False),
                )
            )
            _metrics.webhook_queue_depth.set(depth or 0)
    except Exception:
        logger.warning("metrics: failed to query webhook_queue_depth")

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
