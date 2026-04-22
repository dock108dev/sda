"""Tests for the Stripe webhook retry task and dead-letter admin endpoint.

Covers:
- process_stripe_webhook_event Celery task (idempotency, retry, dead-letter)
- GET /api/admin/webhooks/dead-letters
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from celery.exceptions import Retry
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.dependencies.auth import verify_api_key
from app.routers.admin.webhooks import router as dead_letter_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHECKOUT_PAYLOAD = json.dumps(
    {
        "id": "evt_task_001",
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_task_abc"}},
    }
)


def _call_task(event_id: str, payload: str, *, retries: int = 0) -> Any:
    """Call the task's underlying function with a controlled retry context."""
    from app.tasks.webhook_retry import process_stripe_webhook_event

    process_stripe_webhook_event.push_request(retries=retries)
    try:
        return process_stripe_webhook_event.run(event_id, payload)
    finally:
        process_stripe_webhook_event.pop_request()


# ---------------------------------------------------------------------------
# Task wrapper unit tests
# ---------------------------------------------------------------------------


class TestProcessStripeWebhookEventTask:

    def test_success_returns_ok(self) -> None:
        with patch("asyncio.new_event_loop") as mock_loop_factory:
            loop = MagicMock()
            loop.run_until_complete = MagicMock(side_effect=lambda c: (c.close(), None)[1])  # no error
            mock_loop_factory.return_value = loop

            result = _call_task("evt_ok", _CHECKOUT_PAYLOAD, retries=0)

        assert result["status"] == "ok"
        assert result["event_id"] == "evt_ok"

    def test_failure_before_max_retries_raises_and_does_not_dead_letter(self) -> None:
        """On non-final failure, an exception propagates (Celery re-queues) and no dead-letter log."""
        exc = RuntimeError("db down")

        with (
            patch("asyncio.new_event_loop") as mock_loop_factory,
            patch("app.tasks.webhook_retry.logger") as mock_logger,
        ):
            loop = MagicMock()
            loop.run_until_complete = MagicMock(side_effect=lambda c: (c.close(), exc)[1])
            mock_loop_factory.return_value = loop

            with pytest.raises(Exception):
                _call_task("evt_retry", _CHECKOUT_PAYLOAD, retries=0)

        # Dead-letter log must NOT fire on a non-final attempt
        for call_args in mock_logger.error.call_args_list:
            extra = call_args.kwargs.get("extra", {})
            assert extra.get("event") != "webhook_dead_letter"

    def test_exponential_backoff_grows_on_each_retry(self) -> None:
        """countdown = base * 2^retry_index — verified via retry() call_args."""
        from app.tasks.webhook_retry import _BACKOFF_BASE_SECONDS, process_stripe_webhook_event

        exc = RuntimeError("fail")
        expected_countdowns = [60, 120, 240]

        for retry_index, expected in zip(range(3), expected_countdowns):
            captured_countdown: list[int] = []

            def _capture_retry(*args, **kwargs):
                captured_countdown.append(kwargs.get("countdown", -1))
                raise RuntimeError("retry raised")

            with patch("asyncio.new_event_loop") as mock_loop_factory:
                loop = MagicMock()
                loop.run_until_complete = MagicMock(side_effect=lambda c: (c.close(), exc)[1])
                mock_loop_factory.return_value = loop

                process_stripe_webhook_event.push_request(retries=retry_index)
                with (
                    patch.object(process_stripe_webhook_event, "retry", side_effect=_capture_retry),
                    pytest.raises(RuntimeError, match="retry raised"),
                ):
                    process_stripe_webhook_event.run("evt_exp", _CHECKOUT_PAYLOAD)
                process_stripe_webhook_event.pop_request()

            assert captured_countdown == [expected], (
                f"retry_index={retry_index}: expected countdown {expected}, got {captured_countdown}"
            )

    def test_final_failure_returns_dead_letter_status(self) -> None:
        """On the 4th attempt (retries==max_retries), emits dead-letter log and returns."""
        exc = RuntimeError("final fail")

        with (
            patch("asyncio.new_event_loop") as mock_loop_factory,
            patch("app.tasks.webhook_retry.logger") as mock_logger,
        ):
            loop = MagicMock()
            loop.run_until_complete = MagicMock(side_effect=lambda c: (c.close(), exc)[1])
            mock_loop_factory.return_value = loop

            result = _call_task("evt_dl", _CHECKOUT_PAYLOAD, retries=3)

        assert result["status"] == "dead_letter"
        assert result["event_id"] == "evt_dl"
        mock_logger.error.assert_called_once()
        log_extra = mock_logger.error.call_args.kwargs["extra"]
        assert log_extra["event"] == "webhook_dead_letter"
        assert log_extra["event_id"] == "evt_dl"

    def test_dead_letter_log_includes_attempt_count(self) -> None:
        exc = RuntimeError("db crash")

        with (
            patch("asyncio.new_event_loop") as mock_loop_factory,
            patch("app.tasks.webhook_retry.logger") as mock_logger,
        ):
            loop = MagicMock()
            loop.run_until_complete = MagicMock(side_effect=lambda c: (c.close(), exc)[1])
            mock_loop_factory.return_value = loop

            _call_task("evt_dl2", _CHECKOUT_PAYLOAD, retries=3)

        extra = mock_logger.error.call_args.kwargs["extra"]
        assert extra["attempts"] == 4  # retries(3) + 1

    def test_idempotent_when_already_processed(self) -> None:
        """_run_and_record returns None → no retry, status=ok."""
        with patch("asyncio.new_event_loop") as mock_loop_factory:
            loop = MagicMock()
            loop.run_until_complete = MagicMock(side_effect=lambda c: (c.close(), None)[1])
            mock_loop_factory.return_value = loop

            result = _call_task("evt_idem", _CHECKOUT_PAYLOAD, retries=0)

        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# _run_and_record unit tests
# ---------------------------------------------------------------------------


class TestRunAndRecord:
    """Tests for the internal _run_and_record async helper."""

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _sf_with_db(self, db: AsyncMock):
        sf = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=db)
        cm.__aexit__ = AsyncMock(return_value=False)
        sf.return_value = cm
        return sf

    def _task_db_ctx(self, db: AsyncMock):
        ctx = MagicMock()
        sf = self._sf_with_db(db)
        ctx.__aenter__ = AsyncMock(return_value=sf)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    def _make_db(self, already_processed: bool = False) -> AsyncMock:
        db = AsyncMock()
        db.scalar = AsyncMock(return_value=MagicMock() if already_processed else None)
        db.execute = AsyncMock(return_value=MagicMock(rowcount=1))
        db.add = MagicMock()
        db.commit = AsyncMock()
        return db

    def test_returns_none_when_event_already_in_processed_events(self) -> None:
        from app.tasks.webhook_retry import _run_and_record

        db = self._make_db(already_processed=True)
        with patch("app.tasks.webhook_retry._task_db", return_value=self._task_db_ctx(db)):
            result = self._run(_run_and_record("evt_seen", _CHECKOUT_PAYLOAD, 1, False))

        assert result is None

    def test_unknown_event_type_is_noop(self) -> None:
        from app.tasks.webhook_retry import _run_and_record

        unknown_payload = json.dumps({
            "id": "evt_unk",
            "type": "some.unknown.event",
            "data": {"object": {"id": "obj_x"}},
        })
        db = self._make_db(already_processed=False)

        with (
            patch("app.tasks.webhook_retry._task_db", return_value=self._task_db_ctx(db)),
            patch("app.tasks.webhook_retry._parse_stripe_event") as mock_construct,
        ):
            ev = MagicMock()
            ev.type = "some.unknown.event"
            mock_construct.return_value = ev
            result = self._run(_run_and_record("evt_unk", unknown_payload, 1, False))

        assert result is None

    def test_handler_success_returns_none(self) -> None:
        from app.tasks.webhook_retry import _run_and_record

        db = self._make_db(already_processed=False)
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"

        async def _ok_handler(_db, _ev):
            pass

        with (
            patch("app.tasks.webhook_retry._task_db", return_value=self._task_db_ctx(db)),
            patch("app.tasks.webhook_retry._parse_stripe_event", return_value=mock_event),
            patch("app.routers.webhooks._mark_processed", new=AsyncMock(return_value=True)),
            patch("app.routers.webhooks._HANDLERS", {"checkout.session.completed": _ok_handler}),
        ):
            result = self._run(_run_and_record("evt_new", _CHECKOUT_PAYLOAD, 1, False))

        assert result is None

    def test_handler_failure_returns_exception(self) -> None:
        from app.tasks.webhook_retry import _run_and_record

        db = self._make_db(already_processed=False)
        handler_exc = RuntimeError("handler blew up")
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"

        async def _fail_handler(_db, _ev):
            raise handler_exc

        with (
            patch("app.tasks.webhook_retry._task_db", return_value=self._task_db_ctx(db)),
            patch("app.tasks.webhook_retry._parse_stripe_event", return_value=mock_event),
            patch("app.routers.webhooks._mark_processed", new=AsyncMock(return_value=True)),
            patch("app.routers.webhooks._HANDLERS", {"checkout.session.completed": _fail_handler}),
        ):
            result = self._run(_run_and_record("evt_fail", _CHECKOUT_PAYLOAD, 1, False))

        assert result is handler_exc

    def test_dead_letter_flag_set_on_last_attempt(self) -> None:
        from app.tasks.webhook_retry import _run_and_record

        db = self._make_db(already_processed=False)
        handler_exc = RuntimeError("persistent fail")
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"

        async def _fail_handler(_db, _ev):
            raise handler_exc

        with (
            patch("app.tasks.webhook_retry._task_db", return_value=self._task_db_ctx(db)),
            patch("app.tasks.webhook_retry._parse_stripe_event", return_value=mock_event),
            patch("app.routers.webhooks._mark_processed", new=AsyncMock(return_value=True)),
            patch("app.routers.webhooks._HANDLERS", {"checkout.session.completed": _fail_handler}),
        ):
            # is_last=True → is_dead_letter must be True on the recorded attempt row
            result = self._run(_run_and_record("evt_dl3", _CHECKOUT_PAYLOAD, 4, True))

        assert result is handler_exc
        added_obj = db.add.call_args[0][0]
        assert added_obj.is_dead_letter is True
        assert added_obj.outcome == "fail"

    def test_success_attempt_recorded_with_correct_outcome(self) -> None:
        from app.tasks.webhook_retry import _run_and_record

        db = self._make_db(already_processed=False)
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"

        async def _ok_handler(_db, _ev):
            pass

        with (
            patch("app.tasks.webhook_retry._task_db", return_value=self._task_db_ctx(db)),
            patch("app.tasks.webhook_retry._parse_stripe_event", return_value=mock_event),
            patch("app.routers.webhooks._mark_processed", new=AsyncMock(return_value=True)),
            patch("app.routers.webhooks._HANDLERS", {"checkout.session.completed": _ok_handler}),
        ):
            self._run(_run_and_record("evt_succ", _CHECKOUT_PAYLOAD, 1, False))

        added_obj = db.add.call_args[0][0]
        assert added_obj.outcome == "success"
        assert added_obj.is_dead_letter is False
        assert added_obj.event_id == "evt_succ"


# ---------------------------------------------------------------------------
# Dead-letter admin endpoint tests
# ---------------------------------------------------------------------------


def _make_dead_letter_app(db: AsyncMock) -> TestClient:
    app = FastAPI()

    async def _override_db():
        yield db

    async def _override_key():
        pass

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[verify_api_key] = _override_key
    app.include_router(dead_letter_router, prefix="/api/admin")
    return TestClient(app)


def _make_attempt_row(
    id: int,
    event_id: str,
    event_type: str = "checkout.session.completed",
    attempt_num: int = 4,
    error_detail: str = "connection error",
) -> MagicMock:
    row = MagicMock()
    row.id = id
    row.event_id = event_id
    row.event_type = event_type
    row.attempt_num = attempt_num
    row.attempted_at = datetime(2026, 4, 21, 12, 0, 0, tzinfo=UTC)
    row.error_detail = error_detail
    row.is_dead_letter = True
    return row


class TestDeadLettersEndpoint:

    def test_empty_dead_letters_returns_200_empty_list(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        client = _make_dead_letter_app(db)
        resp = client.get("/api/admin/webhooks/dead-letters")

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_returns_dead_letter_items(self) -> None:
        db = AsyncMock()
        rows = [
            _make_attempt_row(1, "evt_dl_001", attempt_num=4, error_detail="timeout"),
            _make_attempt_row(2, "evt_dl_002", attempt_num=4, error_detail="conn refused"),
        ]
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        db.execute = AsyncMock(return_value=result)

        client = _make_dead_letter_app(db)
        resp = client.get("/api/admin/webhooks/dead-letters")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        assert body["items"][0]["event_id"] == "evt_dl_001"
        assert body["items"][0]["attempt_num"] == 4
        assert body["items"][0]["error_detail"] == "timeout"
        assert body["items"][1]["event_id"] == "evt_dl_002"

    def test_response_fields_present(self) -> None:
        db = AsyncMock()
        row = _make_attempt_row(10, "evt_fields")
        result = MagicMock()
        result.scalars.return_value.all.return_value = [row]
        db.execute = AsyncMock(return_value=result)

        client = _make_dead_letter_app(db)
        resp = client.get("/api/admin/webhooks/dead-letters")

        item = resp.json()["items"][0]
        for field in ("id", "event_id", "event_type", "attempt_num", "attempted_at", "error_detail"):
            assert field in item, f"missing field: {field}"

    def test_queries_db_once(self) -> None:
        db = AsyncMock()
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=result)

        client = _make_dead_letter_app(db)
        client.get("/api/admin/webhooks/dead-letters")

        db.execute.assert_called_once()
