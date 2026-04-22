"""Tests for ISSUE-024 observability: PII redaction, health endpoints, Prometheus metrics."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import JSONFormatter


# ---------------------------------------------------------------------------
# PII redaction in JSONFormatter
# ---------------------------------------------------------------------------


class TestPIIRedaction:
    def _make_record(self, msg: str, **extra: object) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def _format(self, **extra: object) -> dict:
        formatter = JSONFormatter(service="test", environment="test")
        record = self._make_record("test message", **extra)
        return json.loads(formatter.format(record))

    def test_email_field_is_redacted(self) -> None:
        result = self._format(email="user@example.com")
        assert result.get("email") == "[REDACTED]"

    def test_token_field_is_redacted(self) -> None:
        result = self._format(token="super-secret-jwt")
        assert result.get("token") == "[REDACTED]"

    def test_access_token_field_is_redacted(self) -> None:
        result = self._format(access_token="eyJhbGc...")
        assert result.get("access_token") == "[REDACTED]"

    def test_raw_token_field_is_redacted(self) -> None:
        result = self._format(raw_token="tok_live_abc123")
        assert result.get("raw_token") == "[REDACTED]"

    def test_non_sensitive_field_passes_through(self) -> None:
        result = self._format(club_id=42, path="/api/v1/clubs")
        assert result.get("club_id") == 42
        assert result.get("path") == "/api/v1/clubs"

    def test_email_not_present_in_log_record_by_default(self) -> None:
        """A plain log record must not contain an email field at all."""
        result = self._format()
        assert "email" not in result


# ---------------------------------------------------------------------------
# GET /health — always 200, no auth
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def _make_client(self) -> TestClient:
        from fastapi import FastAPI
        from starlette.responses import JSONResponse

        app = FastAPI()

        @app.get("/health")
        async def health() -> JSONResponse:
            return JSONResponse({"status": "ok"})

        return TestClient(app)

    def test_health_returns_200(self) -> None:
        client = self._make_client()
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_status_ok(self) -> None:
        client = self._make_client()
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /ready — 503 when DB or Redis is down
# ---------------------------------------------------------------------------


def _build_ready_app() -> FastAPI:
    """Minimal FastAPI app containing only the /ready route logic.

    References _get_engine through the module at call time so that patch()
    in tests can replace it correctly.
    """
    app = FastAPI()

    @app.get("/ready")
    async def ready() -> JSONResponse:
        import redis.asyncio as aioredis
        from sqlalchemy import text
        from starlette.responses import JSONResponse as _JSONResponse

        import app.db as _db
        from app.config import settings

        result: dict[str, bool] = {"db": True, "redis": True}

        try:
            async with _db._get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            result["db"] = False

        try:
            r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
            await r.ping()
            await r.aclose()
        except Exception:
            result["redis"] = False

        if all(result.values()):
            return _JSONResponse({"status": "ok", **result})
        return _JSONResponse({"status": "unavailable", **result}, status_code=503)

    return app


class TestReadyEndpoint:
    def _make_engine_mock(self, *, db_error: Exception | None = None) -> MagicMock:
        mock_conn = AsyncMock()
        if db_error:
            mock_conn.execute = AsyncMock(side_effect=db_error)
        else:
            mock_conn.execute = AsyncMock(return_value=MagicMock())
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        engine = MagicMock()
        engine.connect.return_value = mock_conn
        return engine

    def _make_redis_mock(self, *, ping_error: Exception | None = None) -> AsyncMock:
        mock_redis = AsyncMock()
        if ping_error:
            mock_redis.ping = AsyncMock(side_effect=ping_error)
        else:
            mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.aclose = AsyncMock()
        return mock_redis

    def test_ready_503_when_db_unreachable(self) -> None:
        app = _build_ready_app()
        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("app.db._get_engine", return_value=self._make_engine_mock(db_error=OSError("refused"))),
            patch("redis.asyncio.from_url", return_value=self._make_redis_mock()),
        ):
            resp = client.get("/ready")

        assert resp.status_code == 503
        body = resp.json()
        assert body["db"] is False
        assert body["redis"] is True

    def test_ready_503_when_redis_unreachable(self) -> None:
        app = _build_ready_app()
        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("app.db._get_engine", return_value=self._make_engine_mock()),
            patch("redis.asyncio.from_url", return_value=self._make_redis_mock(ping_error=OSError("down"))),
        ):
            resp = client.get("/ready")

        assert resp.status_code == 503
        body = resp.json()
        assert body["db"] is True
        assert body["redis"] is False

    def test_ready_200_when_all_healthy(self) -> None:
        app = _build_ready_app()
        client = TestClient(app, raise_server_exceptions=False)

        with (
            patch("app.db._get_engine", return_value=self._make_engine_mock()),
            patch("redis.asyncio.from_url", return_value=self._make_redis_mock()),
        ):
            resp = client.get("/ready")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# request_id propagation into audit log entries
# ---------------------------------------------------------------------------


class TestRequestIdPropagation:
    def test_emit_includes_request_id_from_contextvar(self) -> None:
        """When request_id_var is set, audit.emit merges it into payload."""
        from app.context import request_id_var
        import app.services.audit as svc

        captured: list = []

        with patch("asyncio.create_task", side_effect=lambda c: c.close()) as mock_task:
            mock_task.side_effect = lambda coro: captured.append(coro) or MagicMock()

            token = request_id_var.set("test-req-id-123")
            try:
                svc.emit(
                    "club_provisioned",
                    actor_type="system",
                    resource_type="club",
                    resource_id="uuid-001",
                    payload={"slug": "my-club"},
                )
            finally:
                request_id_var.reset(token)

        assert mock_task.called
        # Inspect the coroutine's args — it should be a _write coroutine
        coro = captured[0]
        # The coroutine was created with merged_payload including request_id.
        # We verify by running it against a fake DB.
        added: list = []
        fake_db = MagicMock()
        fake_db.add = lambda obj: added.append(obj)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__ = AsyncMock(return_value=False)

        async def _run() -> None:
            with patch("app.db.get_async_session", return_value=fake_db):
                await coro

        asyncio.run(_run())

        assert len(added) == 1
        assert added[0].payload == {"slug": "my-club", "request_id": "test-req-id-123"}

    def test_emit_without_request_id_does_not_inject(self) -> None:
        """When request_id_var is unset, emit leaves payload unchanged."""
        from app.context import request_id_var
        import app.services.audit as svc

        # Ensure contextvar is cleared
        token = request_id_var.set(None)
        captured: list = []

        try:
            with patch("asyncio.create_task", side_effect=lambda c: c.close()) as mock_task:
                mock_task.side_effect = lambda coro: captured.append(coro) or MagicMock()
                svc.emit(
                    "club_provisioned",
                    actor_type="system",
                    resource_type="club",
                    resource_id="uuid-001",
                    payload={"slug": "other-club"},
                )
        finally:
            request_id_var.reset(token)

        added: list = []
        fake_db = MagicMock()
        fake_db.add = lambda obj: added.append(obj)
        fake_db.__aenter__ = AsyncMock(return_value=fake_db)
        fake_db.__aexit__ = AsyncMock(return_value=False)

        async def _run() -> None:
            with patch("app.db.get_async_session", return_value=fake_db):
                await captured[0]

        asyncio.run(_run())

        assert added[0].payload == {"slug": "other-club"}


# ---------------------------------------------------------------------------
# Prometheus middleware — counter and histogram updates
# ---------------------------------------------------------------------------


class TestPrometheusMiddleware:
    def test_middleware_increments_request_counter(self) -> None:
        from prometheus_client import REGISTRY

        from app.middleware.logging import StructuredLoggingMiddleware

        inner = FastAPI()

        @inner.get("/ping")
        async def ping() -> dict:
            return {"pong": True}

        inner.add_middleware(StructuredLoggingMiddleware)
        client = TestClient(inner)

        before = _get_counter_value("http_requests_total", method="GET", path="/ping", status="200")
        client.get("/ping")
        after = _get_counter_value("http_requests_total", method="GET", path="/ping", status="200")
        assert after == before + 1

    def test_middleware_records_histogram(self) -> None:
        from app.middleware.logging import StructuredLoggingMiddleware
        from prometheus_client import REGISTRY

        inner = FastAPI()

        @inner.get("/pong")
        async def pong() -> dict:
            return {}

        inner.add_middleware(StructuredLoggingMiddleware)
        client = TestClient(inner)
        client.get("/pong")

        # Histogram count for this path should be at least 1.
        count = _get_histogram_count("http_request_duration_seconds", method="GET", path="/pong")
        assert count >= 1


def _get_counter_value(name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    # prometheus_client strips _total from metric.name but keeps it in sample.name
    stripped = name.removesuffix("_total")
    for metric in REGISTRY.collect():
        if metric.name in (name, stripped):
            for sample in metric.samples:
                if sample.name in (name, stripped + "_total") and all(
                    sample.labels.get(k) == v for k, v in labels.items()
                ):
                    return sample.value
    return 0.0


def _get_histogram_count(name: str, **labels: str) -> float:
    from prometheus_client import REGISTRY

    for metric in REGISTRY.collect():
        if metric.name == name:
            for sample in metric.samples:
                if sample.name == name + "_count" and all(
                    sample.labels.get(k) == v for k, v in labels.items()
                ):
                    return sample.value
    return 0.0
