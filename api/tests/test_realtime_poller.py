"""Tests for realtime/poller.py catch-up behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.realtime.poller import DBPoller


def _mock_session_factory(execute_result: MagicMock) -> MagicMock:
    """Build a session-factory mock that returns an async session context manager."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=execute_result)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=session)


class TestDBPollerBasics:
    @patch("app.realtime.poller.realtime_manager")
    def test_start_registers_first_subscriber_callback(self, mock_mgr):
        poller = DBPoller()
        poller.start()
        mock_mgr.set_on_first_subscriber.assert_called_once_with(
            poller._on_first_subscriber
        )

    @pytest.mark.asyncio
    async def test_stop_is_noop(self):
        poller = DBPoller()
        await poller.stop()

    def test_stats_empty_dict(self):
        poller = DBPoller()
        assert poller.stats() == {}


class TestDispatch:
    @pytest.mark.asyncio
    async def test_invalid_channel_is_ignored(self):
        poller = DBPoller()
        await poller._on_first_subscriber("invalid:channel")

    @pytest.mark.asyncio
    async def test_on_first_subscriber_dispatches_by_channel_type(self):
        poller = DBPoller()
        poller._catchup_game_summary = AsyncMock()
        poller._catchup_games_list = AsyncMock()
        poller._catchup_fairbet = AsyncMock()

        await poller._on_first_subscriber("game:42:summary")
        poller._catchup_game_summary.assert_called_once_with(42)

        await poller._on_first_subscriber("games:NBA:2026-03-05")
        poller._catchup_games_list.assert_called_once_with("NBA", "2026-03-05")

        await poller._on_first_subscriber("fairbet:odds")
        poller._catchup_fairbet.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_first_subscriber_swallow_errors(self):
        poller = DBPoller()
        poller._catchup_fairbet = AsyncMock(side_effect=RuntimeError("boom"))
        await poller._on_first_subscriber("fairbet:odds")


class TestCatchupGameSummary:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    @patch("app.realtime.poller._get_session_factory")
    async def test_publishes_patch_when_game_found(self, mock_get_sf, mock_mgr):
        mock_mgr.publish = AsyncMock()
        row = MagicMock()
        row.status = "live"
        row.home_score = 100
        row.away_score = 95
        execute_result = MagicMock()
        execute_result.one_or_none.return_value = row
        mock_get_sf.return_value = _mock_session_factory(execute_result)

        poller = DBPoller()
        await poller._catchup_game_summary(42)

        mock_mgr.publish.assert_called_once_with(
            "game:42:summary",
            "game_patch",
            {
                "gameId": "42",
                "patch": {"status": "live", "score": {"home": 100, "away": 95}},
            },
        )

    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    @patch("app.realtime.poller._get_session_factory")
    async def test_no_publish_when_game_missing(self, mock_get_sf, mock_mgr):
        mock_mgr.publish = AsyncMock()
        execute_result = MagicMock()
        execute_result.one_or_none.return_value = None
        mock_get_sf.return_value = _mock_session_factory(execute_result)

        poller = DBPoller()
        await poller._catchup_game_summary(42)

        mock_mgr.publish.assert_not_called()


class TestCatchupGamesList:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    @patch("app.realtime.poller._get_session_factory")
    async def test_publishes_patch_per_game(self, mock_get_sf, mock_mgr):
        mock_mgr.publish = AsyncMock()
        row1 = MagicMock()
        row1.id = 1
        row1.status = "final"
        row1.home_score = 110
        row1.away_score = 105
        row2 = MagicMock()
        row2.id = 2
        row2.status = "live"
        row2.home_score = 70
        row2.away_score = 69
        execute_result = MagicMock()
        execute_result.all.return_value = [row1, row2]
        mock_get_sf.return_value = _mock_session_factory(execute_result)

        poller = DBPoller()
        await poller._catchup_games_list("NBA", "2026-03-05")

        assert mock_mgr.publish.call_count == 2
        mock_mgr.publish.assert_any_call(
            "games:NBA:2026-03-05",
            "game_patch",
            {
                "gameId": "1",
                "patch": {"status": "final", "score": {"home": 110, "away": 105}},
            },
        )
        mock_mgr.publish.assert_any_call(
            "games:NBA:2026-03-05",
            "game_patch",
            {
                "gameId": "2",
                "patch": {"status": "live", "score": {"home": 70, "away": 69}},
            },
        )

    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    @patch("app.realtime.poller._get_session_factory")
    async def test_no_publish_for_empty_list(self, mock_get_sf, mock_mgr):
        mock_mgr.publish = AsyncMock()
        execute_result = MagicMock()
        execute_result.all.return_value = []
        mock_get_sf.return_value = _mock_session_factory(execute_result)

        poller = DBPoller()
        await poller._catchup_games_list("NBA", "2026-03-05")

        mock_mgr.publish.assert_not_called()


class TestCatchupFairbet:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_publishes_refresh_event(self, mock_mgr):
        mock_mgr.publish = AsyncMock()
        poller = DBPoller()
        await poller._catchup_fairbet()
        mock_mgr.publish.assert_called_once_with(
            "fairbet:odds",
            "fairbet_patch",
            {"patch": {"refresh": True, "reason": "initial_subscribe"}},
        )
