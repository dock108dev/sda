"""Admin endpoint: circuit breaker telemetry.

GET /api/admin/circuit-breakers         — in-memory breaker state + 50 recent DB trips.
GET /api/admin/social/playwright-health — Playwright session health from Redis.

Requires admin API key (enforced at router registration level in main.py).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

import redis as _redis_mod
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.db.telemetry import CircuitBreakerTripEvent
from app.services.circuit_breaker_registry import registry

logger = logging.getLogger(__name__)

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

# Redis keys written by the scraper's session_health module.
_HEALTH_KEY = "playwright:session:health"
_CIRCUIT_OPEN_KEY = "playwright:session:circuit_open"
_CONSECUTIVE_FAILURES_KEY = "playwright:session:consecutive_failures"
_CIRCUIT_BREAKER_THRESHOLD = 3


def _get_redis() -> _redis_mod.Redis:
    url = settings.celery_broker_url or settings.redis_url
    return _redis_mod.from_url(url, decode_responses=True)


class BreakerStateResponse(BaseModel):
    model_config = _ALIAS_CFG

    name: str
    is_open: bool
    trip_count: int
    last_trip_reason: Optional[str] = None
    last_trip_at: Optional[datetime] = None
    last_reset_at: Optional[datetime] = None


class TripEventResponse(BaseModel):
    model_config = _ALIAS_CFG

    id: int
    breaker_name: str
    reason: str
    tripped_at: datetime


class CircuitBreakersResponse(BaseModel):
    model_config = _ALIAS_CFG

    breakers: list[BreakerStateResponse]
    recent_trips: list[TripEventResponse]


class PlaywrightHealthResponse(BaseModel):
    model_config = _ALIAS_CFG

    circuit_open: bool
    consecutive_failures: int
    circuit_breaker_threshold: int
    last_check: Optional[dict] = None


@router.get("/circuit-breakers", response_model=CircuitBreakersResponse)
async def get_circuit_breakers(
    db: AsyncSession = Depends(get_db),
) -> CircuitBreakersResponse:
    """Return current state for all registered circuit breakers and recent trip history."""
    breaker_states = [
        BreakerStateResponse(
            name=s.name,
            is_open=s.is_open,
            trip_count=s.trip_count,
            last_trip_reason=s.last_trip_reason,
            last_trip_at=s.last_trip_at,
            last_reset_at=s.last_reset_at,
        )
        for s in registry.get_all()
    ]

    result = await db.execute(
        select(CircuitBreakerTripEvent)
        .order_by(desc(CircuitBreakerTripEvent.tripped_at))
        .limit(50)
    )
    rows = result.scalars().all()
    recent_trips = [
        TripEventResponse(
            id=row.id,
            breaker_name=row.breaker_name,
            reason=row.reason,
            tripped_at=row.tripped_at,
        )
        for row in rows
    ]

    return CircuitBreakersResponse(breakers=breaker_states, recent_trips=recent_trips)


@router.get("/social/playwright-health", response_model=PlaywrightHealthResponse)
async def get_playwright_health() -> PlaywrightHealthResponse:
    """Return the Playwright session health state from Redis.

    Reflects the most recent probe result written by the scraper worker.
    ``circuitOpen: true`` means scraping is suspended until the session is restored.
    """
    try:
        r = _get_redis()
        circuit_open = r.get(_CIRCUIT_OPEN_KEY) == "1"
        raw_failures = r.get(_CONSECUTIVE_FAILURES_KEY)
        consecutive_failures = int(raw_failures) if raw_failures else 0
        raw_health = r.get(_HEALTH_KEY)
        last_check: dict | None = None
        if raw_health:
            try:
                last_check = json.loads(raw_health)
            except Exception:
                pass
    except Exception:
        logger.warning("playwright_health_redis_read_failed", exc_info=True)
        circuit_open = False
        consecutive_failures = 0
        last_check = None

    return PlaywrightHealthResponse(
        circuit_open=circuit_open,
        consecutive_failures=consecutive_failures,
        circuit_breaker_threshold=_CIRCUIT_BREAKER_THRESHOLD,
        last_check=last_check,
    )
