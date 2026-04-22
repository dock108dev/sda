"""Tests for AuditEvent DB model, AuditService, and GET /api/admin/audit endpoint."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.audit import AuditEvent
from app.routers.admin.audit import router


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


def _make_event(
    event_id: str = "evt-001",
    event_type: str = "club_provisioned",
    actor_type: str = "system",
    actor_id: str | None = "claim_abc",
    club_id: int | None = 1,
    resource_type: str = "club",
    resource_id: str = "uuid-001",
    payload: dict | None = None,
    row_id: int = 1,
) -> AuditEvent:
    ev = AuditEvent(
        event_id=event_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        club_id=club_id,
        resource_type=resource_type,
        resource_id=resource_id,
        payload=payload or {"slug": "my-club"},
    )
    ev.id = row_id
    ev.created_at = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    return ev


class _ScalarsResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeDB:
    def __init__(self, rows: list[AuditEvent]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> _ScalarsResult:
        return MagicMock(scalars=lambda: _ScalarsResult(self._rows))

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _make_app(db: _FakeDB) -> TestClient:
    async def _override() -> Any:
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# AuditEvent model
# ---------------------------------------------------------------------------


class TestAuditEventModel:
    def test_tablename(self) -> None:
        assert AuditEvent.__tablename__ == "audit_events"

    def test_required_fields_can_be_set(self) -> None:
        ev = AuditEvent(
            event_id="uuid-x",
            event_type="club_provisioned",
            actor_type="system",
            resource_type="club",
            resource_id="uuid-y",
        )
        assert ev.event_id == "uuid-x"
        assert ev.actor_type == "system"
        assert ev.club_id is None
        assert ev.payload is None


# ---------------------------------------------------------------------------
# AuditService — emit / _write
# ---------------------------------------------------------------------------


class TestAuditService:

    def test_emit_schedules_task(self) -> None:
        """emit() calls asyncio.create_task with the write coroutine."""
        import app.services.audit as svc

        with patch("asyncio.create_task", side_effect=lambda c: c.close()) as mock_create:
            svc.emit(
                "club_provisioned",
                actor_type="system",
                resource_type="club",
                resource_id="uuid-001",
                club_id=1,
            )
            mock_create.assert_called_once()

    def test_write_swallows_exception(self) -> None:
        """_write never raises — failures are logged as warnings."""
        import app.services.audit as svc

        async def _run() -> None:
            with patch("app.db.get_async_session", side_effect=RuntimeError("db down")):
                # Should not raise
                await svc._write(
                    event_type="club_provisioned",
                    actor_type="system",
                    actor_id=None,
                    club_id=None,
                    resource_type="club",
                    resource_id="uuid-001",
                    payload=None,
                )

        asyncio.run(_run())

    def test_write_persists_event(self) -> None:
        """_write creates an AuditEvent row via get_async_session."""
        import app.services.audit as svc

        added: list[Any] = []

        fake_db = MagicMock()
        fake_db.add = lambda obj: added.append(obj)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__ = AsyncMock(return_value=False)

        async def _run() -> None:
            with patch("app.db.get_async_session", return_value=fake_db):
                await svc._write(
                    event_type="subscription_activated",
                    actor_type="webhook",
                    actor_id="cs_test_001",
                    club_id=None,
                    resource_type="subscription",
                    resource_id="cs_test_001",
                    payload={"checkout_session_id": "cs_test_001"},
                )

        asyncio.run(_run())

        assert len(added) == 1
        ev: AuditEvent = added[0]
        assert ev.event_type == "subscription_activated"
        assert ev.actor_type == "webhook"
        assert ev.actor_id == "cs_test_001"
        assert ev.payload == {"checkout_session_id": "cs_test_001"}
        assert ev.event_id is not None


# ---------------------------------------------------------------------------
# GET /audit endpoint
# ---------------------------------------------------------------------------


class TestAuditEndpoint:

    def test_200_returns_events(self) -> None:
        ev = _make_event()
        client = _make_app(_FakeDB([ev]))

        resp = client.get("/audit")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "events" in body
        assert len(body["events"]) == 1
        assert body["events"][0]["event_type"] == "club_provisioned"
        assert body["events"][0]["actor_type"] == "system"

    def test_200_empty_list(self) -> None:
        client = _make_app(_FakeDB([]))

        resp = client.get("/audit")

        assert resp.status_code == 200
        assert resp.json()["events"] == []
        assert resp.json()["next_cursor"] is None

    def test_pagination_next_cursor_present(self) -> None:
        """When more rows exist than limit, next_cursor is set."""
        events = [_make_event(event_id=f"e{i}", row_id=i) for i in range(1, 52)]
        client = _make_app(_FakeDB(events))

        resp = client.get("/audit?limit=50")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 50
        assert body["next_cursor"] == 50  # id of last row in page

    def test_pagination_no_next_cursor_when_at_end(self) -> None:
        events = [_make_event(event_id=f"e{i}", row_id=i) for i in range(1, 6)]
        client = _make_app(_FakeDB(events))

        resp = client.get("/audit?limit=50")

        assert resp.status_code == 200
        assert resp.json()["next_cursor"] is None

    def test_query_params_forwarded(self) -> None:
        """Endpoint accepts club_id, event_type, cursor, limit without error."""
        client = _make_app(_FakeDB([]))

        resp = client.get("/audit?club_id=1&event_type=club_provisioned&limit=10&cursor=999")

        assert resp.status_code == 200

    def test_limit_clamped(self) -> None:
        """limit > 200 returns 422."""
        client = _make_app(_FakeDB([]))
        resp = client.get("/audit?limit=999")
        assert resp.status_code == 422

    def test_response_snake_case_fields(self) -> None:
        ev = _make_event()
        client = _make_app(_FakeDB([ev]))

        body = client.get("/audit").json()
        event = body["events"][0]

        # router uses response_model_by_alias=False → snake_case keys
        assert "event_id" in event
        assert "event_type" in event
        assert "actor_type" in event
        assert "actor_id" in event
        assert "club_id" in event
        assert "resource_type" in event
        assert "resource_id" in event
        assert "created_at" in event


# ---------------------------------------------------------------------------
# Instrumentation smoke tests — verify emit() is called from key paths
# ---------------------------------------------------------------------------


class TestInstrumentationHooks:

    def test_provisioning_emits_club_provisioned(self) -> None:
        """ClubProvisioningService.provision calls audit.emit on new club."""
        from unittest.mock import call

        import app.services.audit as svc
        from app.db.club import Club
        from app.db.golf_pools import GolfPool
        from app.db.onboarding import ClubClaim, OnboardingSession
        from app.db.users import User
        from app.services.provisioning import ClubProvisioningService

        def _r(scalar: Any = None, scalar_one: Any = None, rowcount: int | None = None) -> MagicMock:
            r = MagicMock()
            r.scalar_one_or_none.return_value = scalar
            r.scalar_one.return_value = scalar_one if scalar_one is not None else scalar
            if rowcount is not None:
                r.rowcount = rowcount
            return r

        club = Club(club_id="uuid-1", slug="my-club", name="My Club", plan_id="price_pro", status="active")
        club.id = 7

        class _DB:
            def __init__(self) -> None:
                self._q = [
                    _r(scalar=OnboardingSession(claim_id="c1", session_token="t", plan_id="price_pro", status="claimed")),
                    _r(scalar=ClubClaim(claim_id="c1", club_name="My Club", contact_email="a@b.com", status="new")),
                    _r(scalar=None),       # owner not found
                    _r(rowcount=1),        # insert wins
                    _r(scalar_one=club),   # select club
                ]
                self.added: list[Any] = []
                self.flushed = False

            async def execute(self, _stmt: Any) -> Any:
                return self._q.pop(0)

            def add(self, obj: Any) -> None:
                self.added.append(obj)

            async def flush(self) -> None:
                self.flushed = True

        with patch.object(svc, "emit") as mock_emit:
            asyncio.run(ClubProvisioningService().provision(_DB(), "c1"))

        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args
        assert kwargs[0][0] == "club_provisioned"

    def test_pool_lifecycle_emits_pool_state_transition(self) -> None:
        """PoolStateMachine._apply calls audit.emit after pool state change."""
        from unittest.mock import AsyncMock

        import app.services.audit as svc
        from app.db.golf_pools import GolfPool
        from app.services.pool_lifecycle import PoolStateMachine, PoolStatus

        pool = GolfPool(status="locked", scoring_enabled=False)
        pool.id = 5
        pool.club_id = 2

        fake_db = MagicMock()
        fake_db.add = MagicMock()
        fake_db.flush = AsyncMock()

        with patch.object(svc, "emit") as mock_emit:
            asyncio.run(
                PoolStateMachine(pool, fake_db)._apply(
                    PoolStatus.LOCKED, PoolStatus.LIVE, actor_user_id=99, metadata=None
                )
            )

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "pool_state_transition"
        assert mock_emit.call_args[1]["actor_type"] == "user"
        assert mock_emit.call_args[1]["actor_id"] == "99"

    def test_pool_lifecycle_system_actor_when_no_user(self) -> None:
        """actor_type is 'system' when actor_user_id is None."""
        from unittest.mock import AsyncMock

        import app.services.audit as svc
        from app.db.golf_pools import GolfPool
        from app.services.pool_lifecycle import PoolStateMachine, PoolStatus

        pool = GolfPool(status="live", scoring_enabled=True)
        pool.id = 6
        pool.club_id = None

        fake_db = MagicMock()
        fake_db.add = MagicMock()
        fake_db.flush = AsyncMock()

        with patch.object(svc, "emit") as mock_emit:
            asyncio.run(
                PoolStateMachine(pool, fake_db)._apply(
                    PoolStatus.LIVE, PoolStatus.FINAL, actor_user_id=None, metadata=None
                )
            )

        assert mock_emit.call_args[1]["actor_type"] == "system"
        assert mock_emit.call_args[1]["actor_id"] is None

    def test_webhook_checkout_completed_emits_subscription_activated(self) -> None:
        """_handle_checkout_completed calls audit.emit."""
        import app.services.audit as svc
        from app.routers.webhooks import _handle_checkout_completed

        fake_db = MagicMock()
        fake_db.execute = AsyncMock()
        event = MagicMock()
        event.data.object.id = "cs_test_123"

        with patch.object(svc, "emit") as mock_emit:
            asyncio.run(_handle_checkout_completed(fake_db, event))

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "subscription_activated"

    def test_webhook_subscription_deleted_emits_subscription_cancelled(self) -> None:
        """_handle_subscription_deleted calls audit.emit."""
        import app.services.audit as svc
        from app.routers.webhooks import _handle_subscription_deleted

        fake_db = MagicMock()
        fake_db.execute = AsyncMock()
        event = MagicMock()
        event.data.object.id = "sub_test_456"

        with patch.object(svc, "emit") as mock_emit:
            asyncio.run(_handle_subscription_deleted(fake_db, event))

        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0] == "subscription_cancelled"
