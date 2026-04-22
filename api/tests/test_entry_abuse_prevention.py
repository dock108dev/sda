"""Tests for public entry rate limiting, honeypot, and per-email limit (ISSUE-011)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.golf_pools import GolfPool
from app.services import entry_rate_limit as erl
from app.services import fairbet_runtime as fr


def _make_result(scalar: Any = None) -> MagicMock:
    r = MagicMock()
    r.scalar_one_or_none.return_value = scalar
    r.scalar.return_value = scalar
    return r


class _QueueDB:
    def __init__(self, *results: Any) -> None:
        self._queue: list[Any] = list(results)

    async def execute(self, _stmt: Any) -> Any:
        if not self._queue:
            return _make_result(scalar=0)
        return self._queue.pop(0)

    async def get(self, _model: Any, _pk: Any) -> Any:
        item = self._queue.pop(0)
        if isinstance(item, MagicMock) and hasattr(item, "scalar_one_or_none"):
            return item.scalar_one_or_none()
        return item

    def add(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


class _Pipe:
    def __init__(self, redis_obj: Any) -> None:
        self.r = redis_obj
        self.ops: list[tuple[Any, ...]] = []

    def zremrangebyscore(self, key: str, low: int, high: int) -> "_Pipe":
        self.ops.append(("zrem", key, low, high))
        return self

    def zcard(self, key: str) -> "_Pipe":
        self.ops.append(("zcard", key))
        return self

    def zadd(self, key: str, payload: dict[str, int]) -> "_Pipe":
        self.ops.append(("zadd", key, payload))
        return self

    def expire(self, key: str, ttl: int) -> "_Pipe":
        self.ops.append(("expire", key, ttl))
        return self

    def execute(self) -> list[Any]:
        out: list[Any] = []
        for op in self.ops:
            if op[0] == "zrem":
                _, key, _, high = op
                members = self.r.zsets.setdefault(key, {})
                stale = [m for m, score in members.items() if score <= high]
                for m in stale:
                    del members[m]
                out.append(len(stale))
            elif op[0] == "zcard":
                _, key = op
                out.append(len(self.r.zsets.get(key, {})))
            elif op[0] == "zadd":
                _, key, payload = op
                members = self.r.zsets.setdefault(key, {})
                members.update(payload)
                out.append(1)
            elif op[0] == "expire":
                out.append(True)
        self.ops = []
        return out


class _FakeRedis:
    def __init__(self) -> None:
        self.zsets: dict[str, dict[str, int]] = {}

    def pipeline(self) -> _Pipe:
        return _Pipe(self)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    fake = _FakeRedis()
    monkeypatch.setattr(fr, "get_redis_client", lambda: fake)
    monkeypatch.setattr(fr, "_redis_error_until", 0.0)
    return fake


def _pool(**overrides: Any) -> GolfPool:
    p = GolfPool(code="t", name="Test", club_code="test-club", status="open")
    p.id = 10
    p.club_id = None
    p.club_code = "test-club"
    p.entry_deadline = None
    p.max_entries_per_email = None
    p.rules_json = None  # validate_entry_picks short-circuits with 422
    p.tournament_id = 5
    return p


def _build_app(pool: GolfPool, *extra_results: Any) -> TestClient:
    from app.routers.golf import router as golf_router

    async def _override() -> Any:
        db = _QueueDB(pool, *extra_results)
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override
    app.include_router(golf_router)
    return TestClient(app, raise_server_exceptions=False)


class TestHoneypot:
    def test_populated_website_returns_201_without_db_write(self) -> None:
        """Honeypot populated: 201 but never touches the DB layer."""
        from app.routers.golf import router as golf_router

        called: dict[str, bool] = {"executed": False, "got": False}

        class _SpyDB:
            async def execute(self, _stmt: Any) -> Any:
                called["executed"] = True
                return _make_result(scalar=0)

            async def get(self, _m: Any, _pk: Any) -> Any:
                called["got"] = True
                return _pool()

            def add(self, _o: Any) -> None: ...
            async def flush(self) -> None: ...
            async def refresh(self, _o: Any) -> None: ...
            async def commit(self) -> None: ...
            async def rollback(self) -> None: ...
            async def close(self) -> None: ...

        async def _override() -> Any:
            yield _SpyDB()

        app = FastAPI()
        app.dependency_overrides[get_db] = _override
        app.include_router(golf_router)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.post(
            "/api/golf/pools/10/entries",
            json={
                "email": "bot@example.com",
                "picks": [],
                "website": "http://spam.example.com",
            },
        )

        assert resp.status_code == 201, resp.text
        assert called["executed"] is False
        assert called["got"] is False

    def test_empty_website_processes_normally(self, fake_redis: _FakeRedis) -> None:
        client = _build_app(_pool(), _make_result(scalar=0))
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "human@example.com", "picks": [], "website": ""},
        )
        # Proceeds past honeypot; validation rejects (rules invalid) with 422
        assert resp.status_code == 422


class TestRateLimit:
    def test_sixth_submission_returns_429_with_retry_after(
        self, fake_redis: _FakeRedis, caplog: pytest.LogCaptureFixture
    ) -> None:
        pool = _pool()
        # First 5 submissions succeed (pass rate-limit); validation error is fine.
        for _ in range(5):
            client = _build_app(pool, _make_result(scalar=0))
            resp = client.post(
                "/api/golf/pools/10/entries",
                json={"email": "u@example.com", "picks": []},
            )
            assert resp.status_code != 429, resp.text

        # 6th submission hits the rate limit.
        caplog.set_level(logging.WARNING, logger="app.services.entry_rate_limit")
        client = _build_app(pool, _make_result(scalar=0))
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "u@example.com", "picks": []},
        )
        assert resp.status_code == 429, resp.text
        assert "Retry-After" in resp.headers
        assert int(resp.headers["Retry-After"]) > 0

        # Structured abuse log emitted.
        abuse_records = [r for r in caplog.records if getattr(r, "event", None) == "entry_abuse"]
        assert abuse_records, "expected entry_abuse log record"

    def test_rate_limit_counter_in_redis(self, fake_redis: _FakeRedis) -> None:
        pool = _pool()
        client = _build_app(pool, _make_result(scalar=0))
        client.post(
            "/api/golf/pools/10/entries",
            json={"email": "u@example.com", "picks": []},
        )
        keys_with_entries_prefix = [k for k in fake_redis.zsets if "entries" in k]
        assert keys_with_entries_prefix, "rate-limit counter should live in Redis"

    def test_key_isolates_different_clubs(self, fake_redis: _FakeRedis) -> None:
        """Rate-limit buckets are per-club-per-IP; exhausting one club doesn't block another."""
        pool_a = _pool()
        pool_a.club_code = "club-a"
        for _ in range(5):
            client = _build_app(pool_a, _make_result(scalar=0))
            client.post(
                "/api/golf/pools/10/entries",
                json={"email": "u@example.com", "picks": []},
            )

        pool_b = _pool()
        pool_b.club_code = "club-b"
        client = _build_app(pool_b, _make_result(scalar=0))
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "u@example.com", "picks": []},
        )
        assert resp.status_code != 429


class TestMaxEntriesPerEmail:
    def test_exceeding_default_limit_returns_422_with_code(
        self, fake_redis: _FakeRedis
    ) -> None:
        pool = _pool()
        pool.max_entries_per_email = None  # default 3 kicks in
        client = _build_app(pool, _make_result(scalar=3))  # already at 3
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "u@example.com", "picks": []},
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert body["detail"]["code"] == "ENTRY_LIMIT_EXCEEDED"

    def test_explicit_max_honored(self, fake_redis: _FakeRedis) -> None:
        pool = _pool()
        pool.max_entries_per_email = 1
        client = _build_app(pool, _make_result(scalar=1))
        resp = client.post(
            "/api/golf/pools/10/entries",
            json={"email": "u@example.com", "picks": []},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "ENTRY_LIMIT_EXCEEDED"
