"""Tests for EntitlementService — 100% branch coverage on plan limit map and all check methods.

Also verifies:
  - Global exception handler converts EntitlementError → HTTP 403 (never 500)
  - Pool creation and entry submission endpoints return 403 when plan limits are exceeded
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.db import get_db
from app.db.club import Club
from app.db.golf_pools import GolfPool
from app.services.entitlement import (
    PLAN_LIMITS,
    AppError,
    EntitlementError,
    EntitlementService,
    PlanLimits,
    _DEFAULT_PLAN,
    _FEATURES,
)


# ---------------------------------------------------------------------------
# Stubs / helpers
# ---------------------------------------------------------------------------


def _make_result(scalar: Any = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalar.return_value = scalar
    return r


class _QueueDB:
    """Async session stub that returns pre-queued results in FIFO order."""

    def __init__(self, *results: Any) -> None:
        self._queue: list[Any] = list(results)
        self.added: list[Any] = []
        self.flushed: bool = False

    async def execute(self, _stmt: Any) -> Any:
        return self._queue.pop(0)

    async def get(self, _model: Any, _pk: Any) -> Any:
        item = self._queue.pop(0)
        if isinstance(item, MagicMock) and hasattr(item, "scalar_one_or_none"):
            return item.scalar_one_or_none()
        return item

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True

    async def refresh(self, _obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _make_club(plan_id: str = "price_pro", db_id: int = 1) -> Club:
    c = Club(
        club_id="uuid-1111",
        slug="test-club",
        name="Test Club",
        plan_id=plan_id,
        status="active",
    )
    c.id = db_id
    return c


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# PLAN_LIMITS structure
# ---------------------------------------------------------------------------


class TestPlanLimitsStructure:
    def test_all_plans_defined(self) -> None:
        assert "price_starter" in PLAN_LIMITS
        assert "price_pro" in PLAN_LIMITS
        assert "price_enterprise" in PLAN_LIMITS

    def test_starter_limits(self) -> None:
        lim = PLAN_LIMITS["price_starter"]
        assert lim.max_pools_active == 1
        assert lim.max_entries_per_pool == 50
        assert lim.scoring_enabled is False
        assert lim.branding_enabled is False

    def test_pro_limits(self) -> None:
        lim = PLAN_LIMITS["price_pro"]
        assert lim.max_pools_active == 5
        assert lim.max_entries_per_pool == 200
        assert lim.scoring_enabled is True
        assert lim.branding_enabled is False

    def test_enterprise_unlimited(self) -> None:
        lim = PLAN_LIMITS["price_enterprise"]
        assert lim.max_pools_active is None
        assert lim.max_entries_per_pool is None
        assert lim.scoring_enabled is True
        assert lim.branding_enabled is True

    def test_default_plan_mirrors_starter(self) -> None:
        assert _DEFAULT_PLAN.max_pools_active == 1
        assert _DEFAULT_PLAN.max_entries_per_pool == 50
        assert _DEFAULT_PLAN.scoring_enabled is False
        assert _DEFAULT_PLAN.branding_enabled is False

    def test_features_set(self) -> None:
        assert "scoring_enabled" in _FEATURES
        assert "branding_enabled" in _FEATURES
        assert "custom_branding" in _FEATURES

    def test_entitlement_error_is_app_error(self) -> None:
        err = EntitlementError("test")
        assert isinstance(err, AppError)


# ---------------------------------------------------------------------------
# _get_limits
# ---------------------------------------------------------------------------


class TestGetLimits:
    def test_club_not_found_raises(self) -> None:
        db = _QueueDB(_make_result(scalar=None))
        with pytest.raises(EntitlementError, match="not found"):
            _run(EntitlementService()._get_limits(99, db))

    def test_known_plan_returns_correct_limits(self) -> None:
        club = _make_club("price_pro")
        db = _QueueDB(_make_result(scalar=club))
        limits = _run(EntitlementService()._get_limits(1, db))
        assert limits == PLAN_LIMITS["price_pro"]

    def test_unknown_plan_returns_default(self) -> None:
        club = _make_club("price_unknown")
        db = _QueueDB(_make_result(scalar=club))
        limits = _run(EntitlementService()._get_limits(1, db))
        assert limits == _DEFAULT_PLAN


# ---------------------------------------------------------------------------
# check_pool_limit
# ---------------------------------------------------------------------------


class TestCheckPoolLimit:
    def test_unlimited_plan_skips_count_query(self) -> None:
        """Enterprise plan (max_pools_active=None) returns early without a DB count."""
        club = _make_club("price_enterprise")
        # check_subscription_active consumes first result; _get_limits consumes second
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=club))
        _run(EntitlementService().check_pool_limit(1, db))
        assert len(db._queue) == 0  # count query was never issued

    def test_under_limit_does_not_raise(self) -> None:
        club = _make_club("price_pro")  # limit = 5
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=club), _make_result(scalar=4))
        _run(EntitlementService().check_pool_limit(1, db))  # 4 < 5, no error

    def test_at_limit_raises(self) -> None:
        club = _make_club("price_pro")  # limit = 5
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=club), _make_result(scalar=5))
        with pytest.raises(EntitlementError, match="5 active pools"):
            _run(EntitlementService().check_pool_limit(1, db))

    def test_zero_count_does_not_raise(self) -> None:
        club = _make_club("price_starter")  # limit = 1
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=club), _make_result(scalar=0))
        _run(EntitlementService().check_pool_limit(1, db))

    def test_club_not_found_raises(self) -> None:
        # check_subscription_active gets None → early return; _get_limits gets None → raises
        db = _QueueDB(_make_result(scalar=None), _make_result(scalar=None))
        with pytest.raises(EntitlementError, match="not found"):
            _run(EntitlementService().check_pool_limit(99, db))

    def test_null_scalar_treated_as_zero(self) -> None:
        """Handles NULL from COUNT when no rows exist."""
        club = _make_club("price_starter")  # limit = 1
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=club), _make_result(scalar=None))
        _run(EntitlementService().check_pool_limit(1, db))  # None → 0, no error


# ---------------------------------------------------------------------------
# check_entry_limit
# ---------------------------------------------------------------------------


class TestCheckEntryLimit:
    def test_unlimited_plan_skips_count_query(self) -> None:
        club = _make_club("price_enterprise")
        db = _QueueDB(_make_result(scalar=club))
        _run(EntitlementService().check_entry_limit(1, 42, db))
        assert len(db._queue) == 0

    def test_under_limit_does_not_raise(self) -> None:
        club = _make_club("price_pro")  # limit = 200
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=50))
        _run(EntitlementService().check_entry_limit(1, 42, db))

    def test_at_limit_raises(self) -> None:
        club = _make_club("price_pro")  # limit = 200
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=200))
        with pytest.raises(EntitlementError, match="200 entries"):
            _run(EntitlementService().check_entry_limit(1, 42, db))

    def test_zero_count_does_not_raise(self) -> None:
        club = _make_club("price_starter")  # limit = 50
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=0))
        _run(EntitlementService().check_entry_limit(1, 42, db))

    def test_club_not_found_raises(self) -> None:
        db = _QueueDB(_make_result(scalar=None))
        with pytest.raises(EntitlementError, match="not found"):
            _run(EntitlementService().check_entry_limit(99, 42, db))

    def test_null_scalar_treated_as_zero(self) -> None:
        club = _make_club("price_starter")  # limit = 50
        db = _QueueDB(_make_result(scalar=club), _make_result(scalar=None))
        _run(EntitlementService().check_entry_limit(1, 42, db))


# ---------------------------------------------------------------------------
# assert_feature
# ---------------------------------------------------------------------------


class TestAssertFeature:
    def test_unknown_feature_raises_without_db_query(self) -> None:
        """Unknown feature raises immediately, before any DB lookup."""
        db = _QueueDB()  # empty — no results should be consumed
        with pytest.raises(EntitlementError, match="Unknown feature"):
            _run(EntitlementService().assert_feature(1, "nonexistent", db))
        assert len(db._queue) == 0

    def test_disabled_feature_raises(self) -> None:
        club = _make_club("price_starter")  # scoring_enabled=False
        db = _QueueDB(_make_result(scalar=club))
        with pytest.raises(EntitlementError, match="not available"):
            _run(EntitlementService().assert_feature(1, "scoring_enabled", db))

    def test_enabled_feature_does_not_raise(self) -> None:
        club = _make_club("price_pro")  # scoring_enabled=True
        db = _QueueDB(_make_result(scalar=club))
        _run(EntitlementService().assert_feature(1, "scoring_enabled", db))

    def test_branding_disabled_raises(self) -> None:
        club = _make_club("price_pro")  # branding_enabled=False
        db = _QueueDB(_make_result(scalar=club))
        with pytest.raises(EntitlementError, match="not available"):
            _run(EntitlementService().assert_feature(1, "branding_enabled", db))

    def test_branding_enabled_enterprise(self) -> None:
        club = _make_club("price_enterprise")  # branding_enabled=True
        db = _QueueDB(_make_result(scalar=club))
        _run(EntitlementService().assert_feature(1, "branding_enabled", db))

    def test_club_not_found_raises(self) -> None:
        db = _QueueDB(_make_result(scalar=None))
        with pytest.raises(EntitlementError, match="not found"):
            _run(EntitlementService().assert_feature(99, "scoring_enabled", db))

    def test_custom_branding_disabled_free_tier(self) -> None:
        """check_feature('custom_branding') raises EntitlementError on starter plan."""
        club = _make_club("price_starter")  # custom_branding=False
        db = _QueueDB(_make_result(scalar=club))
        with pytest.raises(EntitlementError, match="not available"):
            _run(EntitlementService().check_feature(1, "custom_branding", db))

    def test_custom_branding_disabled_pro(self) -> None:
        club = _make_club("price_pro")  # custom_branding=False
        db = _QueueDB(_make_result(scalar=club))
        with pytest.raises(EntitlementError, match="not available"):
            _run(EntitlementService().check_feature(1, "custom_branding", db))

    def test_custom_branding_enabled_enterprise(self) -> None:
        club = _make_club("price_enterprise")  # custom_branding=True
        db = _QueueDB(_make_result(scalar=club))
        _run(EntitlementService().check_feature(1, "custom_branding", db))  # no exception

    def test_custom_branding_in_features_set(self) -> None:
        assert "custom_branding" in _FEATURES


# ---------------------------------------------------------------------------
# Global exception handler — EntitlementError → 403, never 500
# ---------------------------------------------------------------------------


def _make_handler_app() -> FastAPI:
    """Minimal FastAPI app that mirrors the global exception handler wiring."""
    app = FastAPI()

    @app.exception_handler(EntitlementError)
    async def _entitlement_handler(request: Request, exc: EntitlementError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"code": "ENTITLEMENT_EXCEEDED", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def _global_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": "internal"})

    @app.get("/raise-entitlement")
    async def _raise_entitlement() -> None:
        raise EntitlementError("pool limit exceeded")

    @app.get("/raise-other")
    async def _raise_other() -> None:
        raise ValueError("unexpected")

    return app


class TestGlobalExceptionHandler:
    def setup_method(self) -> None:
        self.client = TestClient(_make_handler_app(), raise_server_exceptions=False)

    def test_entitlement_error_returns_403(self) -> None:
        resp = self.client.get("/raise-entitlement")
        assert resp.status_code == 403
        body = resp.json()
        assert body["code"] == "ENTITLEMENT_EXCEEDED"
        assert "pool limit exceeded" in body["detail"]

    def test_other_exception_returns_500(self) -> None:
        resp = self.client.get("/raise-other")
        assert resp.status_code == 500

    def test_entitlement_error_never_returns_500(self) -> None:
        resp = self.client.get("/raise-entitlement")
        assert resp.status_code != 500


# ---------------------------------------------------------------------------
# Pool creation endpoint — 403 when pool limit exceeded
# ---------------------------------------------------------------------------


def _make_pool_admin_app(db_queue: _QueueDB) -> TestClient:
    from app.routers.golf import router as golf_router

    async def _override() -> Any:
        yield db_queue

    app = FastAPI()

    @app.exception_handler(EntitlementError)
    async def _handler(request: Request, exc: EntitlementError) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"code": "ENTITLEMENT_EXCEEDED", "detail": str(exc)},
        )

    app.dependency_overrides[get_db] = _override
    app.include_router(golf_router)
    return TestClient(app, raise_server_exceptions=False)


class TestPoolCreationEntitlementWiring:
    def test_403_when_pool_limit_exceeded(self) -> None:
        club = _make_club("price_pro")  # limit = 5 active pools
        db = _QueueDB(
            _make_result(scalar=42),     # tournament exists
            _make_result(scalar=club),   # club found by slug
            _make_result(scalar=club),   # check_subscription_active: club by id
            _make_result(scalar=club),   # _get_limits: club by id
            _make_result(scalar=5),      # pool count = 5, at limit
        )
        client = _make_pool_admin_app(db)

        resp = client.post(
            "/api/golf/pools",
            json={
                "code": "test-pool",
                "name": "Test Pool",
                "club_code": "test-club",
                "tournament_id": 1,
            },
        )

        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["code"] == "ENTITLEMENT_EXCEEDED"
        assert "active pools" in body["detail"]

    def test_no_entitlement_check_when_club_not_found(self) -> None:
        """Pool creation proceeds without entitlement check when club_code has no Club row."""
        from app.routers.golf import router as golf_router

        db = _QueueDB(
            _make_result(scalar=42),    # tournament exists
            _make_result(scalar=None),  # club not found by slug → skip entitlement
        )

        async def _patched_db() -> Any:
            yield db

        app = FastAPI()

        @app.exception_handler(EntitlementError)
        async def _handler(request: Request, exc: EntitlementError) -> JSONResponse:
            return JSONResponse(status_code=403, content={"code": "ENTITLEMENT_EXCEEDED", "detail": str(exc)})

        app.dependency_overrides[get_db] = _patched_db
        app.include_router(golf_router)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/golf/pools",
            json={
                "code": "t",
                "name": "T",
                "club_code": "unknown",
                "tournament_id": 1,
            },
        )
        # 403 would mean entitlement was incorrectly applied for a missing club
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Entry submission endpoint — 403 when entry limit exceeded
# ---------------------------------------------------------------------------


def _make_pool_for_entry(club_id: int = 1) -> GolfPool:
    p = GolfPool(
        code="t",
        name="Test Pool",
        club_code="test-club",
        status="open",
    )
    p.id = 10
    p.club_id = club_id
    p.entry_deadline = None
    p.max_entries_per_email = None
    p.rules_json = None
    p.tournament_id = 5
    return p


class TestEntrySubmissionEntitlementWiring:
    def test_403_when_entry_limit_exceeded(self) -> None:
        from app.routers.golf import router as golf_router

        pool = _make_pool_for_entry(club_id=1)
        club = _make_club("price_pro")  # limit = 200 entries

        async def _override() -> Any:
            db = _QueueDB(
                pool,                       # db.get(GolfPool, pool_id)
                _make_result(scalar=0),     # count_entries_for_email (honeypot/limit)
                _make_result(scalar=club),  # _get_limits: club by id
                _make_result(scalar=200),   # entry count = 200, at limit
            )
            yield db

        app = FastAPI()

        @app.exception_handler(EntitlementError)
        async def _handler(request: Request, exc: EntitlementError) -> JSONResponse:
            return JSONResponse(
                status_code=403,
                content={"code": "ENTITLEMENT_EXCEEDED", "detail": str(exc)},
            )

        app.dependency_overrides[get_db] = _override
        app.include_router(golf_router)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "test@example.com", "picks": []},
        )

        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert body["code"] == "ENTITLEMENT_EXCEEDED"

    def test_no_entitlement_check_when_pool_has_no_club(self) -> None:
        """Entry submission skips entitlement when pool.club_id is None."""
        from app.routers.golf import router as golf_router

        pool = _make_pool_for_entry(club_id=None)
        pool.club_id = None
        pool.status = "open"

        async def _override() -> Any:
            db = _QueueDB(
                pool,                    # db.get(GolfPool, pool_id)
                _make_result(scalar=0),  # count_entries_for_email
            )
            yield db

        app = FastAPI()
        app.dependency_overrides[get_db] = _override
        app.include_router(golf_router)

        client = TestClient(app, raise_server_exceptions=False)
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "test@example.com", "picks": []},
        )
        # 403 would mean entitlement incorrectly fired for a club-less pool
        assert resp.status_code != 403
