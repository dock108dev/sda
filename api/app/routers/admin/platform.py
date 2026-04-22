"""Admin SPA platform endpoints.

Powers the `SuperAdminDashboard` in the admin.dock108.dev SPA:

- GET /api/admin/stats        — one-shot 5-tile summary (cached 60s in Redis).
- GET /api/admin/poll-health  — per-pool scraper freshness for the polled
                                live-tournament health widget.

Auth model: gated only by ``verify_api_key`` (admin-tier ``API_KEY``).
No ``require_admin`` JWT check — the admin SPA reaches this backend via a
same-origin nginx proxy that injects the admin API key, and Caddy Basic
Auth in front of the SPA already scopes access to the operator.

Wire format is **snake_case** by design — the frontend's ``src/types/domain.ts``
expects snake_case. The router's response models declare
``alias_generator=to_camel`` to satisfy the repo's camelCase lint
(``scripts/lint_camel_case_schemas.py``) but the routes themselves pass
``response_model_by_alias=False`` so the on-the-wire field names are the
native snake_case field identifiers.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import AsyncGenerator
from zoneinfo import ZoneInfo

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PLAN_PRICES, settings
from app.db import get_db
from app.db.golf import GolfTournament
from app.db.golf_pools import GolfPool, GolfPoolEntry, GolfPoolScoreRun
from app.db.onboarding import ClubClaim
from app.db.stripe import StripeSubscription

logger = logging.getLogger(__name__)

router = APIRouter()

_ALIAS_CFG = ConfigDict(alias_generator=to_camel, populate_by_name=True)

_STATS_CACHE_KEY = "admin:stats:v1"
_STATS_CACHE_TTL = 60  # seconds


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """Yield an async Redis client; close on teardown."""
    client: aioredis.Redis = aioredis.from_url(
        settings.redis_url, decode_responses=True
    )
    try:
        yield client
    finally:
        await client.aclose()


# A pool's data is "stale" during an active tournament window if no
# successful scoring run has completed within this interval.
_STALE_AFTER = timedelta(minutes=30)

# Pool-status buckets used by the stats + poll-health queries.
_POOL_STATUSES_LIVE = ("open", "locked", "live")
_POOL_STATUSES_COUNTED = ("open", "locked", "live", "final")

# Tournament-window window of day in ET (rough Thursday 07:00 → Sunday 20:00).
_TOURNAMENT_WINDOW_TZ = ZoneInfo("America/New_York")
_TOURNAMENT_WINDOW_START_TIME = time(7, 0)
_TOURNAMENT_WINDOW_END_TIME = time(20, 0)


class AdminStatsResponse(BaseModel):
    model_config = _ALIAS_CFG

    total_pools: int
    total_entries: int
    active_clubs: int
    mrr_cents: int
    pending_claims: int


class TournamentPollHealth(BaseModel):
    model_config = _ALIAS_CFG

    pool_id: int
    pool_name: str
    tournament_name: str
    last_polled_at: datetime | None
    is_in_window: bool
    is_stale: bool


class AdminPollHealthResponse(BaseModel):
    model_config = _ALIAS_CFG

    tournaments: list[TournamentPollHealth]
    checked_at: datetime


def _tournament_window_bounds(
    start_date: date, end_date: date | None
) -> tuple[datetime, datetime]:
    """Return UTC (start, end) datetimes for a tournament's play window.

    Uses 07:00 ET on start_date → 20:00 ET on end_date (or start_date + 3
    days when end_date is missing) as a rough "tournament is playing right
    now" envelope. This is intentionally generous on the edges — missing
    by a few hours is fine; the 30-minute staleness threshold is the part
    that matters.
    """
    if end_date is None:
        end_date = start_date + timedelta(days=3)
    start = datetime.combine(
        start_date, _TOURNAMENT_WINDOW_START_TIME, tzinfo=_TOURNAMENT_WINDOW_TZ
    ).astimezone(UTC)
    end = datetime.combine(
        end_date, _TOURNAMENT_WINDOW_END_TIME, tzinfo=_TOURNAMENT_WINDOW_TZ
    ).astimezone(UTC)
    return start, end


@router.get(
    "/stats",
    response_model=AdminStatsResponse,
    response_model_by_alias=False,
)
async def get_admin_stats(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
) -> AdminStatsResponse:
    """Summary metrics for the admin dashboard tile grid.

    All fields are required integers — zero (not null) when empty.
    Result is cached in Redis for 60 seconds to avoid hot queries.
    """
    cached = await redis.get(_STATS_CACHE_KEY)
    if cached:
        return AdminStatsResponse(**json.loads(cached))

    total_pools = await db.scalar(
        select(func.count(GolfPool.id)).where(
            GolfPool.status.in_(_POOL_STATUSES_COUNTED)
        )
    )
    total_entries = await db.scalar(select(func.count(GolfPoolEntry.id)))
    active_clubs = await db.scalar(
        select(func.count(func.distinct(GolfPool.club_code))).where(
            GolfPool.status.in_(_POOL_STATUSES_LIVE)
        )
    )
    pending_claims = await db.scalar(
        select(func.count(ClubClaim.id)).where(ClubClaim.status == "new")
    )

    sub_result = await db.execute(
        select(StripeSubscription.plan_id).where(StripeSubscription.status == "active")
    )
    mrr_cents = sum(PLAN_PRICES.get(plan_id, 0) for (plan_id,) in sub_result.all())

    stats = AdminStatsResponse(
        total_pools=int(total_pools or 0),
        total_entries=int(total_entries or 0),
        active_clubs=int(active_clubs or 0),
        mrr_cents=mrr_cents,
        pending_claims=int(pending_claims or 0),
    )
    await redis.setex(_STATS_CACHE_KEY, _STATS_CACHE_TTL, json.dumps(stats.model_dump()))
    return stats


@router.get(
    "/poll-health",
    response_model=AdminPollHealthResponse,
    response_model_by_alias=False,
)
async def get_poll_health(
    db: AsyncSession = Depends(get_db),
) -> AdminPollHealthResponse:
    """Per-pool scraper freshness for the admin dashboard health widget.

    One row per pool where ``status IN (open, locked, live)`` AND
    ``scoring_enabled = true``. ``is_stale`` is true only inside the
    tournament play window and only when the most recent successful
    scoring run is older than 30 minutes (or missing).
    """
    now = datetime.now(UTC)

    pools_result = await db.execute(
        select(
            GolfPool.id,
            GolfPool.name,
            GolfTournament.id,
            GolfTournament.event_name,
            GolfTournament.start_date,
            GolfTournament.end_date,
        )
        .join(GolfTournament, GolfPool.tournament_id == GolfTournament.id)
        .where(
            GolfPool.status.in_(_POOL_STATUSES_LIVE),
            GolfPool.scoring_enabled.is_(True),
        )
        .order_by(GolfPool.id)
    )
    pools = pools_result.all()

    tournaments: list[TournamentPollHealth] = []
    for pool_id, pool_name, tournament_id, event_name, start_date, end_date in pools:
        last_polled_at = await db.scalar(
            select(func.max(GolfPoolScoreRun.completed_at)).where(
                GolfPoolScoreRun.tournament_id == tournament_id,
                GolfPoolScoreRun.status == "success",
            )
        )

        window_start, window_end = _tournament_window_bounds(start_date, end_date)
        is_in_window = window_start <= now <= window_end

        if not is_in_window:
            is_stale = False
        elif last_polled_at is None:
            is_stale = True
        else:
            polled = last_polled_at
            if polled.tzinfo is None:
                polled = polled.replace(tzinfo=UTC)
            is_stale = (now - polled) > _STALE_AFTER

        tournaments.append(
            TournamentPollHealth(
                pool_id=pool_id,
                pool_name=pool_name,
                tournament_name=event_name,
                last_polled_at=last_polled_at,
                is_in_window=is_in_window,
                is_stale=is_stale,
            )
        )

    return AdminPollHealthResponse(tournaments=tournaments, checked_at=now)
