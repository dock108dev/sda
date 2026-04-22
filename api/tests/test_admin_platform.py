"""Tests for the admin SPA platform endpoints.

GET /api/admin/stats        — 5-tile dashboard summary (Redis-cached 60s).
GET /api/admin/poll-health  — per-pool scraper freshness.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies.auth import verify_api_key
from app.routers.admin.platform import (
    _STATS_CACHE_KEY,
    _tournament_window_bounds,
    get_redis,
    router,
)


# ---------------------------------------------------------------------------
# Fake Redis
# ---------------------------------------------------------------------------

class _FakeRedis:
    """Minimal in-memory Redis stand-in for unit tests."""

    def __init__(self, preloaded: str | None = None) -> None:
        self._store: dict[str, str] = {}
        if preloaded is not None:
            self._store[_STATS_CACHE_KEY] = preloaded

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _make_app(
    *,
    stats_scalars: list[Any] | None = None,
    sub_plans: list[str] | None = None,
    pool_rows: list[tuple] | None = None,
    poll_scalars: list[Any] | None = None,
    redis_preload: str | None = None,
    require_api_key: bool = False,
) -> TestClient:
    """Build a TestClient wired to a fake AsyncSession and fake Redis.

    - ``stats_scalars``: queue of return values for the /stats route's four
      ``db.scalar(...)`` calls: total_pools, total_entries, active_clubs,
      pending_claims.
    - ``sub_plans``: list of plan_id strings for active subscriptions returned
      by the /stats execute call.
    - ``pool_rows``: rows returned by the /poll-health route's pool query.
    - ``poll_scalars``: one scalar result per pool row for last_polled_at.
    - ``redis_preload``: if set, the fake Redis starts with a pre-cached JSON
      string under _STATS_CACHE_KEY (simulates a warm cache hit).
    - ``require_api_key``: mount the real verify_api_key dependency.
    """
    stats_queue = list(stats_scalars or [])
    poll_queue = list(poll_scalars or [])

    db = AsyncMock()

    async def _scalar(*_args, **_kwargs) -> Any:
        if stats_queue:
            return stats_queue.pop(0)
        if poll_queue:
            return poll_queue.pop(0)
        return None

    db.scalar.side_effect = _scalar

    # When sub_plans is explicitly provided (even []) it's a stats test —
    # the first execute call is the subscription query, the second is pools.
    # When sub_plans is None it's a poll-health test — execute returns pool rows only.
    pool_exec = MagicMock()
    pool_exec.all.return_value = pool_rows or []

    if sub_plans is not None:
        sub_exec = MagicMock()
        sub_exec.all.return_value = [(p,) for p in sub_plans]
        db.execute.side_effect = [sub_exec, pool_exec]
    else:
        db.execute.return_value = pool_exec

    fake_redis = _FakeRedis(preloaded=redis_preload)

    async def _get_db_override():
        yield db

    async def _get_redis_override():
        yield fake_redis

    app = FastAPI()
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_redis] = _get_redis_override
    if require_api_key:
        app.include_router(
            router,
            prefix="/api/admin",
            dependencies=[__import__("fastapi").Depends(verify_api_key)],
        )
    else:
        app.include_router(router, prefix="/api/admin")
    return TestClient(app)


# ---------------------------------------------------------------------------
# /api/admin/stats — basic responses
# ---------------------------------------------------------------------------

class TestAdminStats:

    def test_empty_db_returns_zeros(self) -> None:
        client = _make_app(stats_scalars=[0, 0, 0, 0], sub_plans=[])
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "total_pools": 0,
            "total_entries": 0,
            "active_clubs": 0,
            "mrr_cents": 0,
            "pending_claims": 0,
        }

    def test_populated_stats(self) -> None:
        client = _make_app(stats_scalars=[1, 5, 1, 2], sub_plans=[])
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body == {
            "total_pools": 1,
            "total_entries": 5,
            "active_clubs": 1,
            "mrr_cents": 0,
            "pending_claims": 2,
        }

    def test_null_scalars_coerce_to_zero(self) -> None:
        client = _make_app(stats_scalars=[None, None, None, None], sub_plans=[])
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pools"] == 0
        assert body["total_entries"] == 0
        assert body["active_clubs"] == 0
        assert body["mrr_cents"] == 0
        assert body["pending_claims"] == 0

    def test_response_shape_is_snake_case_and_strict(self) -> None:
        client = _make_app(stats_scalars=[3, 142, 2, 1], sub_plans=[])
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body.keys()) == {
            "total_pools",
            "total_entries",
            "active_clubs",
            "mrr_cents",
            "pending_claims",
        }
        for camel in ("totalPools", "totalEntries", "activeClubs", "mrrCents", "pendingClaims"):
            assert camel not in body

    def test_without_api_key_is_401(self) -> None:
        """Regression: /api/admin/stats must reject calls lacking the admin API key."""

        async def _raise_missing():
            raise HTTPException(
                status_code=401,
                detail="Missing API key",
                headers={"WWW-Authenticate": "ApiKey"},
            )

        app = FastAPI()

        async def _get_db_override():
            yield AsyncMock()

        async def _get_redis_override():
            yield _FakeRedis()

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_redis] = _get_redis_override
        app.dependency_overrides[verify_api_key] = _raise_missing

        from fastapi import Depends

        app.include_router(
            router,
            prefix="/api/admin",
            dependencies=[Depends(verify_api_key)],
        )
        client = TestClient(app)
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# /api/admin/stats — MRR computation
# ---------------------------------------------------------------------------

class TestAdminStatsMrr:

    def test_two_active_subscriptions_sum_correctly(self) -> None:
        """Two active subs (starter + pro) should produce 2900 + 9900 = 12800."""
        client = _make_app(
            stats_scalars=[0, 0, 0, 0],
            sub_plans=["price_starter", "price_pro"],
        )
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["mrr_cents"] == 12800

    def test_enterprise_subscription(self) -> None:
        client = _make_app(
            stats_scalars=[0, 0, 0, 0],
            sub_plans=["price_enterprise"],
        )
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["mrr_cents"] == 29900

    def test_unknown_plan_id_contributes_zero(self) -> None:
        """Unknown plan_id not in PLAN_PRICES must not crash and contributes 0."""
        client = _make_app(
            stats_scalars=[0, 0, 0, 0],
            sub_plans=["price_unknown_future_plan", "price_pro"],
        )
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["mrr_cents"] == 9900

    def test_no_active_subscriptions(self) -> None:
        client = _make_app(stats_scalars=[0, 0, 0, 0], sub_plans=[])
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["mrr_cents"] == 0


# ---------------------------------------------------------------------------
# /api/admin/stats — Redis caching
# ---------------------------------------------------------------------------

class TestAdminStatsCache:

    def test_cache_miss_populates_cache(self) -> None:
        """First call (no cache) computes stats and writes to Redis."""
        fake_redis = _FakeRedis()

        db = AsyncMock()
        db.scalar.side_effect = [10, 50, 3, 1]
        sub_exec = MagicMock()
        sub_exec.all.return_value = [("price_pro",)]
        db.execute.return_value = sub_exec

        app = FastAPI()

        async def _get_db_override():
            yield db

        async def _get_redis_override():
            yield fake_redis

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_redis] = _get_redis_override
        app.include_router(router, prefix="/api/admin")
        client = TestClient(app)

        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["mrr_cents"] == 9900
        assert body["pending_claims"] == 1

        # Cache should now be populated.
        assert _STATS_CACHE_KEY in fake_redis._store
        cached = json.loads(fake_redis._store[_STATS_CACHE_KEY])
        assert cached["mrr_cents"] == 9900

    def test_cache_hit_skips_db(self) -> None:
        """Second call within 60s must serve from cache without hitting the DB."""
        preloaded = json.dumps({
            "total_pools": 7,
            "total_entries": 99,
            "active_clubs": 4,
            "mrr_cents": 29900,
            "pending_claims": 3,
        })
        db = AsyncMock()
        # If DB is called, the test fails via unexpected call assertion.
        db.scalar.side_effect = AssertionError("DB should not be queried on cache hit")
        db.execute.side_effect = AssertionError("DB should not be queried on cache hit")

        app = FastAPI()

        async def _get_db_override():
            yield db

        async def _get_redis_override():
            yield _FakeRedis(preloaded=preloaded)

        app.dependency_overrides[get_db] = _get_db_override
        app.dependency_overrides[get_redis] = _get_redis_override
        app.include_router(router, prefix="/api/admin")
        client = TestClient(app)

        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_pools"] == 7
        assert body["mrr_cents"] == 29900
        assert body["pending_claims"] == 3

    def test_pending_claims_count_is_correct(self) -> None:
        """pending_claims reflects ClubClaim rows with status='new'."""
        client = _make_app(
            stats_scalars=[0, 0, 0, 5],
            sub_plans=[],
        )
        resp = client.get("/api/admin/stats")
        assert resp.status_code == 200
        assert resp.json()["pending_claims"] == 5


# ---------------------------------------------------------------------------
# /api/admin/poll-health
# ---------------------------------------------------------------------------

_POOL_ID = 1
_TOURNEY_ID = 10
_POOL_NAME = "RVCC Masters Pool 2026"
_EVENT_NAME = "The Masters 2026"

_IN_WINDOW_DAY = date(2026, 4, 10)   # Friday of Masters week
_OUT_WINDOW_DAY = date(2025, 4, 10)  # prior year → off window
_NOW_IN_WINDOW = datetime(2026, 4, 10, 18, 0, tzinfo=UTC)  # ~14:00 ET
_NOW_OUT_WINDOW = datetime(2026, 5, 1, 18, 0, tzinfo=UTC)


def _pool_row(start: date, end: date) -> tuple:
    return (_POOL_ID, _POOL_NAME, _TOURNEY_ID, _EVENT_NAME, start, end)


class TestPollHealth:

    def test_no_live_pools_returns_empty_list(self) -> None:
        client = _make_app(pool_rows=[])
        with patch(
            "app.routers.admin.platform.datetime"
        ) as dt:
            dt.now.return_value = _NOW_IN_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["tournaments"] == []
        assert body["checked_at"]

    def test_in_window_recent_poll_is_not_stale(self) -> None:
        polled = _NOW_IN_WINDOW - timedelta(minutes=5)
        client = _make_app(
            pool_rows=[_pool_row(_IN_WINDOW_DAY, _IN_WINDOW_DAY + timedelta(days=2))],
            poll_scalars=[polled],
        )
        with patch("app.routers.admin.platform.datetime") as dt:
            dt.now.return_value = _NOW_IN_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        row = resp.json()["tournaments"][0]
        assert row["pool_id"] == _POOL_ID
        assert row["is_in_window"] is True
        assert row["is_stale"] is False
        assert row["last_polled_at"] is not None

    def test_in_window_old_poll_is_stale(self) -> None:
        polled = _NOW_IN_WINDOW - timedelta(minutes=45)
        client = _make_app(
            pool_rows=[_pool_row(_IN_WINDOW_DAY, _IN_WINDOW_DAY + timedelta(days=2))],
            poll_scalars=[polled],
        )
        with patch("app.routers.admin.platform.datetime") as dt:
            dt.now.return_value = _NOW_IN_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        row = resp.json()["tournaments"][0]
        assert row["is_in_window"] is True
        assert row["is_stale"] is True

    def test_in_window_never_polled_is_stale(self) -> None:
        client = _make_app(
            pool_rows=[_pool_row(_IN_WINDOW_DAY, _IN_WINDOW_DAY + timedelta(days=2))],
            poll_scalars=[None],
        )
        with patch("app.routers.admin.platform.datetime") as dt:
            dt.now.return_value = _NOW_IN_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        row = resp.json()["tournaments"][0]
        assert row["is_in_window"] is True
        assert row["is_stale"] is True
        assert row["last_polled_at"] is None

    def test_off_window_old_poll_is_not_stale(self) -> None:
        """Window rule wins — off-window pools never surface as stale."""
        polled = _NOW_OUT_WINDOW - timedelta(minutes=45)
        client = _make_app(
            pool_rows=[_pool_row(_OUT_WINDOW_DAY, _OUT_WINDOW_DAY + timedelta(days=2))],
            poll_scalars=[polled],
        )
        with patch("app.routers.admin.platform.datetime") as dt:
            dt.now.return_value = _NOW_OUT_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        row = resp.json()["tournaments"][0]
        assert row["is_in_window"] is False
        assert row["is_stale"] is False

    def test_naive_last_polled_at_treated_as_utc(self) -> None:
        """Legacy rows may have naive datetimes; they must still compute staleness."""
        polled_naive = (_NOW_IN_WINDOW - timedelta(minutes=5)).replace(tzinfo=None)
        client = _make_app(
            pool_rows=[_pool_row(_IN_WINDOW_DAY, _IN_WINDOW_DAY + timedelta(days=2))],
            poll_scalars=[polled_naive],
        )
        with patch("app.routers.admin.platform.datetime") as dt:
            dt.now.return_value = _NOW_IN_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        row = resp.json()["tournaments"][0]
        assert row["is_stale"] is False

    def test_checked_at_is_close_to_now(self) -> None:
        client = _make_app(pool_rows=[])
        resp = client.get("/api/admin/poll-health")
        assert resp.status_code == 200
        checked_at = datetime.fromisoformat(
            resp.json()["checked_at"].replace("Z", "+00:00")
        )
        drift = abs((datetime.now(UTC) - checked_at).total_seconds())
        assert drift < 5.0

    def test_response_shape_is_snake_case(self) -> None:
        polled = datetime(2026, 4, 10, 17, 55, tzinfo=UTC)
        client = _make_app(
            pool_rows=[_pool_row(_IN_WINDOW_DAY, _IN_WINDOW_DAY + timedelta(days=2))],
            poll_scalars=[polled],
        )
        with patch("app.routers.admin.platform.datetime") as dt:
            dt.now.return_value = _NOW_IN_WINDOW
            dt.combine.side_effect = datetime.combine
            resp = client.get("/api/admin/poll-health")
        body = resp.json()
        assert set(body.keys()) == {"tournaments", "checked_at"}
        row = body["tournaments"][0]
        assert set(row.keys()) == {
            "pool_id",
            "pool_name",
            "tournament_name",
            "last_polled_at",
            "is_in_window",
            "is_stale",
        }
        for camel in ("poolId", "poolName", "tournamentName", "lastPolledAt"):
            assert camel not in row


# ---------------------------------------------------------------------------
# _tournament_window_bounds helper
# ---------------------------------------------------------------------------

class TestTournamentWindowBounds:

    def test_end_date_defaults_to_start_plus_three_days(self) -> None:
        start = date(2026, 4, 9)
        ws, we = _tournament_window_bounds(start, None)
        # +3 days → 2026-04-12 20:00 ET
        assert we.date() in {date(2026, 4, 12), date(2026, 4, 13)}  # ET→UTC offset
        assert ws < we

    def test_explicit_end_date_is_respected(self) -> None:
        start = date(2026, 4, 9)
        end = date(2026, 4, 12)
        ws, we = _tournament_window_bounds(start, end)
        assert ws < we
        # The window should be at least three full days.
        assert (we - ws) >= timedelta(days=3)


@pytest.fixture(autouse=True)
def _reset_overrides() -> None:
    yield
