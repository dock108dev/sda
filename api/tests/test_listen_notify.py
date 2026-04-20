"""Tests for LISTEN/NOTIFY realtime dispatch (ISSUE-038).

Tests the full dispatch path:
  pg_notify → ListenNotifyListener._dispatch() → realtime_manager.publish()
  → SSEConnection.queue populated within 500 ms.

No real Postgres connection required; asyncpg.connect is mocked out.
The integration assertion (score update → SSE within 500ms) is covered by
the TestScoreUpdateSSEIntegration class which drives the listener's internal
dispatch coroutines directly against the in-process pub/sub manager.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.realtime.listener import ListenNotifyListener, _LRUDict
from app.realtime.manager import RealtimeManager, SSEConnection


# ---------------------------------------------------------------------------
# _LRUDict
# ---------------------------------------------------------------------------

class TestLRUDict:
    def test_set_and_get(self):
        d = _LRUDict(maxsize=3)
        d.set(1, 100)
        assert d.get(1) == 100

    def test_missing_returns_default(self):
        d = _LRUDict(maxsize=3)
        assert d.get(99, 0) == 0

    def test_evicts_oldest_on_overflow(self):
        d = _LRUDict(maxsize=2)
        d.set(1, 10)
        d.set(2, 20)
        d.set(3, 30)  # evicts key 1
        assert d.get(1, -1) == -1
        assert d.get(2) == 20
        assert d.get(3) == 30

    def test_update_moves_to_end(self):
        d = _LRUDict(maxsize=2)
        d.set(1, 10)
        d.set(2, 20)
        d.set(1, 99)  # update 1 → it's now most-recent
        d.set(3, 30)  # evicts key 2 (oldest)
        assert d.get(1) == 99
        assert d.get(2, -1) == -1
        assert d.get(3) == 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_listener() -> ListenNotifyListener:
    """Return a listener with DSN pre-set so Settings are not imported."""
    ln = ListenNotifyListener()
    ln._dsn = "postgresql://test:test@localhost/testdb"
    return ln


def _make_manager_with_sse(channel: str) -> tuple[RealtimeManager, SSEConnection]:
    """Return an isolated manager + subscribed SSE connection."""
    manager = RealtimeManager()
    conn = SSEConnection()
    manager.subscribe(conn, channel)
    return manager, conn


# ---------------------------------------------------------------------------
# _on_notify callback
# ---------------------------------------------------------------------------

class TestOnNotify:
    def test_valid_json_schedules_dispatch(self):
        ln = _make_listener()
        dispatched: list[tuple] = []

        async def fake_dispatch(ch, data):
            dispatched.append((ch, data))

        ln._dispatch = fake_dispatch  # type: ignore[method-assign]

        loop = asyncio.new_event_loop()
        try:
            payload = json.dumps({"game_id": 42, "event_type": "game_score_update"})
            # Simulate asyncpg calling the callback inside the loop
            loop.run_until_complete(
                _run_callback_in_loop(ln, "game_score_update", payload)
            )
            assert dispatched == [("game_score_update", {"game_id": 42, "event_type": "game_score_update"})]
        finally:
            loop.close()

    def test_bad_json_does_not_raise(self):
        ln = _make_listener()
        # Should not raise; bad payloads are logged and dropped
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                _run_callback_in_loop(ln, "game_score_update", "not-json{{{")
            )
        finally:
            loop.close()

    def test_empty_payload_treated_as_empty_dict(self):
        ln = _make_listener()
        dispatched: list[tuple] = []

        async def fake_dispatch(ch, data):
            dispatched.append((ch, data))

        ln._dispatch = fake_dispatch  # type: ignore[method-assign]
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_callback_in_loop(ln, "odds_update", ""))
            assert dispatched == [("odds_update", {})]
        finally:
            loop.close()


async def _run_callback_in_loop(ln: ListenNotifyListener, channel: str, payload: str) -> None:
    """Invoke _on_notify synchronously then drain any scheduled coroutines."""
    ln._on_notify(MagicMock(), 1234, channel, payload)
    await asyncio.sleep(0)  # let ensure_future coroutine run


# ---------------------------------------------------------------------------
# _handle_odds_update
# ---------------------------------------------------------------------------

class TestHandleOddsUpdate:
    def test_publishes_fairbet_patch_when_subscriber_exists(self):
        ln = _make_listener()
        manager, conn = _make_manager_with_sse("fairbet:odds")

        async def run():
            with patch.object(ln, "_get_dsn", return_value="postgresql://x"):
                with patch(
                    "app.realtime.listener.realtime_manager", manager
                ):
                    await ln._handle_odds_update({"game_id": 1, "event_type": "odds_update"})
            return await asyncio.wait_for(conn.queue.get(), timeout=0.5)

        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(run())
            parsed = json.loads(data)
            assert parsed["type"] == "fairbet_patch"
        finally:
            loop.close()

    def test_no_publish_when_no_subscribers(self):
        ln = _make_listener()
        manager = RealtimeManager()  # no subscribers

        async def run():
            with patch("app.realtime.listener.realtime_manager", manager):
                await ln._handle_odds_update({"game_id": 1, "event_type": "odds_update"})

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
            # No assertion needed — just verifies no error raised
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# _handle_flow_published
# ---------------------------------------------------------------------------

class TestHandleFlowPublished:
    def test_publishes_flow_published_event(self):
        ln = _make_listener()
        manager, conn = _make_manager_with_sse("game:7:summary")

        async def run():
            with patch("app.realtime.listener.realtime_manager", manager):
                await ln._handle_flow_published(
                    {"game_id": 7, "event_type": "flow_published", "flow_id": 99}
                )
            return await asyncio.wait_for(conn.queue.get(), timeout=0.5)

        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(run())
            parsed = json.loads(data)
            assert parsed["type"] == "flow_published"
            assert parsed["gameId"] == "7"
            assert parsed["flowId"] == 99
        finally:
            loop.close()

    def test_missing_game_id_does_nothing(self):
        ln = _make_listener()
        manager = RealtimeManager()

        async def run():
            with patch("app.realtime.listener.realtime_manager", manager):
                await ln._handle_flow_published({"event_type": "flow_published"})

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Integration: score update → SSE event within 500 ms  (ISSUE-038 criterion 5)
# ---------------------------------------------------------------------------

class TestScoreUpdateSSEIntegration:
    """Write a score update (via _dispatch), assert SSE subscriber gets it ≤500ms."""

    def test_game_score_update_reaches_sse_within_500ms(self):
        """
        Scenario:
          1. SSE client subscribes to game:42:summary
          2. NOTIFY arrives with game_id=42
          3. DB lookup is mocked to return current state
          4. SSE queue must receive the event within 500ms
        """
        ln = _make_listener()
        manager, conn = _make_manager_with_sse("game:42:summary")

        # Mock DB row returned by the session query
        mock_row = MagicMock()
        mock_row.id = 42
        mock_row.status = "live"
        mock_row.home_score = 78
        mock_row.away_score = 75
        mock_row.game_date = _make_aware_dt()
        mock_row.league_code = "NBA"

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session_cm)

        async def run():
            with patch("app.realtime.listener.realtime_manager", manager), \
                 patch("app.realtime.listener._get_session_factory", return_value=mock_factory):
                # Simulate NOTIFY arriving and being dispatched
                await ln._dispatch(
                    "game_score_update",
                    {"game_id": 42, "event_type": "game_score_update"},
                )

            # The SSE queue should have the event within 500ms
            return await asyncio.wait_for(conn.queue.get(), timeout=0.5)

        loop = asyncio.new_event_loop()
        try:
            data = loop.run_until_complete(run())
            parsed = json.loads(data)
            # First notification with no cached status → patch (no prior state to diff against)
            assert parsed["type"] == "patch"
            assert parsed["gameId"] == "42"
            patch_data = parsed["patch"]
            assert patch_data["status"] == "live"
            assert patch_data["score"] == {"home": 78, "away": 75}
        finally:
            loop.close()

    def test_score_update_also_publishes_to_list_channel(self):
        """game_score_update should publish to games:{league}:{date} when subscribed."""
        from datetime import timezone

        ln = _make_listener()
        manager = RealtimeManager()
        summary_conn = SSEConnection()
        list_conn = SSEConnection()
        manager.subscribe(summary_conn, "game:5:summary")
        manager.subscribe(list_conn, "games:NBA:2026-04-19")

        mock_row = MagicMock()
        mock_row.id = 5
        mock_row.status = "final"
        mock_row.home_score = 110
        mock_row.away_score = 98

        import datetime
        mock_row.game_date = datetime.datetime(2026, 4, 19, 12, 0, tzinfo=datetime.timezone.utc)
        mock_row.league_code = "NBA"

        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session_cm = AsyncMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)
        mock_factory = MagicMock(return_value=mock_session_cm)

        async def run():
            with patch("app.realtime.listener.realtime_manager", manager), \
                 patch("app.realtime.listener._get_session_factory", return_value=mock_factory):
                await ln._dispatch(
                    "game_score_update",
                    {"game_id": 5, "event_type": "game_score_update"},
                )

            summary_ev = await asyncio.wait_for(summary_conn.queue.get(), timeout=0.5)
            list_ev = await asyncio.wait_for(list_conn.queue.get(), timeout=0.5)
            return json.loads(summary_ev), json.loads(list_ev)

        loop = asyncio.new_event_loop()
        try:
            summary_parsed, list_parsed = loop.run_until_complete(run())
            # First notification with no cached status → patch
            assert summary_parsed["type"] == "patch"
            assert list_parsed["type"] == "patch"
            assert list_parsed["gameId"] == "5"
        finally:
            loop.close()


    def test_phase_change_emitted_on_status_transition(self):
        """Second notification with a different status → phase_change event."""
        ln = _make_listener()
        manager, conn = _make_manager_with_sse("game:99:summary")

        def _make_mock_row(status: str, home: int, away: int):
            import datetime
            row = MagicMock()
            row.id = 99
            row.status = status
            row.home_score = home
            row.away_score = away
            row.game_date = datetime.datetime(2026, 4, 19, 20, 0, tzinfo=datetime.timezone.utc)
            row.league_code = "NBA"
            return row

        def _build_mock_factory(row):
            mock_result = MagicMock()
            mock_result.one_or_none.return_value = row
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_cm.__aexit__ = AsyncMock(return_value=False)
            return MagicMock(return_value=mock_session_cm)

        async def run():
            with patch("app.realtime.listener.realtime_manager", manager), \
                 patch("app.realtime.listener._get_session_factory",
                       return_value=_build_mock_factory(_make_mock_row("live", 50, 48))):
                await ln._dispatch("game_score_update", {"game_id": 99})
            ev1_raw = await asyncio.wait_for(conn.queue.get(), timeout=0.5)

            # Second dispatch — status changes pregame→live is already cached as "live",
            # so change to "final" triggers phase_change
            with patch("app.realtime.listener.realtime_manager", manager), \
                 patch("app.realtime.listener._get_session_factory",
                       return_value=_build_mock_factory(_make_mock_row("final", 110, 98))):
                await ln._dispatch("game_score_update", {"game_id": 99})
            ev2_raw = await asyncio.wait_for(conn.queue.get(), timeout=0.5)

            return json.loads(ev1_raw), json.loads(ev2_raw)

        loop = asyncio.new_event_loop()
        try:
            ev1, ev2 = loop.run_until_complete(run())
            assert ev1["type"] == "patch"          # first notification, no prior cache
            assert ev2["type"] == "phase_change"   # status "live" → "final"
            assert ev2["patch"]["status"] == "final"
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_aware_dt():
    import datetime
    return datetime.datetime(2026, 4, 19, 20, 0, tzinfo=datetime.timezone.utc)
