"""Tests for realtime/poller.py — DBPoller and _LRUSet."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.realtime.poller import DBPoller, _LRUSet


# ---------------------------------------------------------------------------
# _LRUSet
# ---------------------------------------------------------------------------

class TestLRUSet:
    def test_add_and_contains(self):
        s = _LRUSet(maxsize=5)
        s.add(1)
        assert 1 in s
        assert 2 not in s

    def test_evicts_oldest_when_full(self):
        s = _LRUSet(maxsize=3)
        s.add(1)
        s.add(2)
        s.add(3)
        s.add(4)  # evicts 1
        assert 1 not in s
        assert 4 in s
        assert len(s) == 3

    def test_readd_moves_to_end(self):
        s = _LRUSet(maxsize=3)
        s.add(1)
        s.add(2)
        s.add(3)
        s.add(1)  # re-add 1, moves to end
        s.add(4)  # evicts 2 (not 1 since 1 was refreshed)
        assert 1 in s
        assert 2 not in s

    def test_len(self):
        s = _LRUSet(maxsize=10)
        s.add(10)
        s.add(20)
        assert len(s) == 2


# ---------------------------------------------------------------------------
# DBPoller init + stats
# ---------------------------------------------------------------------------

class TestDBPollerInit:
    def test_init_creates_poller(self):
        poller = DBPoller()
        assert poller._poll_count == {"games": 0, "pbp": 0, "fairbet": 0}
        assert poller._tasks == []

    def test_stats_returns_dict(self):
        poller = DBPoller()
        stats = poller.stats()
        assert "poll_count" in stats
        assert "tracked_games" in stats
        assert "tracked_pbp_games" in stats
        assert "last_poll_duration_ms" in stats


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------

class TestDBPollerStartStop:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_start_creates_tasks(self, mock_mgr):
        poller = DBPoller()
        poller._poll_games_loop = AsyncMock()
        poller._poll_pbp_loop = AsyncMock()
        poller._poll_fairbet_loop = AsyncMock()

        poller.start()
        assert len(poller._tasks) == 3
        mock_mgr.set_on_first_subscriber.assert_called_once()

        await poller.stop()
        assert poller._tasks == []


# ---------------------------------------------------------------------------
# Catch-up callbacks
# ---------------------------------------------------------------------------

class TestDBPollerCatchup:
    @pytest.mark.asyncio
    async def test_on_first_subscriber_invalid_channel(self):
        poller = DBPoller()
        # Should not raise on invalid channel
        await poller._on_first_subscriber("invalid:channel")

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_catchup_game_summary(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        poller = DBPoller()
        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_row = MagicMock()
        mock_row.status = "live"
        mock_row.home_score = 100
        mock_row.away_score = 95
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = mock_row
        mock_session.execute = AsyncMock(return_value=mock_result)

        await poller._catchup_game_summary(42)
        mock_mgr.publish.assert_called_once()
        call_args = mock_mgr.publish.call_args
        assert call_args[0][0] == "game:42:summary"
        assert call_args[0][1] == "game_patch"

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_catchup_game_summary_no_row(self, mock_mgr, mock_sf):
        poller = DBPoller()
        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        await poller._catchup_game_summary(42)
        mock_mgr.publish.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_catchup_games_list(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        poller = DBPoller()
        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.status = "final"
        mock_row.home_score = 110
        mock_row.away_score = 105
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)

        await poller._catchup_games_list("NBA", "2026-03-05")
        mock_mgr.publish.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_catchup_fairbet(self, mock_mgr):
        mock_mgr.publish = AsyncMock()
        poller = DBPoller()
        await poller._catchup_fairbet()
        mock_mgr.publish.assert_called_once_with(
            "fairbet:odds", "fairbet_patch",
            {"patch": {"refresh": True, "reason": "initial_subscribe"}},
        )

    @pytest.mark.asyncio
    async def test_on_first_subscriber_dispatches(self):
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


# ---------------------------------------------------------------------------
# _poll_games
# ---------------------------------------------------------------------------

class TestPollGames:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_games_no_subscribers_skips(self, mock_mgr):
        mock_mgr.active_channels.return_value = set()
        poller = DBPoller()
        await poller._poll_games()
        # Should not query DB

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_games_emits_on_change(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        mock_mgr.active_channels.return_value = {"game:1:summary"}
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        now = datetime.now(UTC)
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.league_id = 1
        mock_row.game_date = now
        mock_row.status = "live"
        mock_row.home_score = 50
        mock_row.away_score = 48
        mock_row.updated_at = now
        mock_row.league_code = "NBA"
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        await poller._poll_games()

        assert poller._poll_count["games"] == 1
        mock_mgr.publish.assert_called()

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_games_dedupes_by_updated_at(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        mock_mgr.active_channels.return_value = {"game:1:summary"}
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        now = datetime.now(UTC)
        mock_row = MagicMock()
        mock_row.id = 1
        mock_row.league_id = 1
        mock_row.game_date = now
        mock_row.status = "live"
        mock_row.home_score = 50
        mock_row.away_score = 48
        mock_row.updated_at = now
        mock_row.league_code = "NBA"
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        # First poll emits
        await poller._poll_games()
        assert mock_mgr.publish.call_count >= 1

        # Second poll with same updated_at should not re-emit
        mock_mgr.publish.reset_mock()
        await poller._poll_games()
        mock_mgr.publish.assert_not_called()


# ---------------------------------------------------------------------------
# _poll_pbp
# ---------------------------------------------------------------------------

class TestPollPBP:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_pbp_no_subscribers_skips(self, mock_mgr):
        mock_mgr.active_channels.return_value = set()
        poller = DBPoller()
        await poller._poll_pbp()

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_pbp_emits_new_plays(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        mock_mgr.active_channels.return_value = {"game:1:pbp"}
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_play = MagicMock()
        mock_play.id = 100
        mock_play.game_id = 1
        mock_play.play_index = 1
        mock_play.created_at = datetime.now(UTC)
        mock_play.play_type = "shot"
        mock_play.description = "3-pointer made"
        mock_play.raw_data = None
        mock_play.home_score = 3
        mock_play.away_score = 0
        mock_play.quarter = 1
        mock_play.game_clock = "11:30"
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_play]
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        await poller._poll_pbp()

        assert poller._poll_count["pbp"] == 1
        mock_mgr.publish.assert_called_once()
        call_args = mock_mgr.publish.call_args
        assert call_args[0][0] == "game:1:pbp"
        assert call_args[0][1] == "pbp_append"

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_pbp_dedupes(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        mock_mgr.active_channels.return_value = {"game:1:pbp"}
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_play = MagicMock()
        mock_play.id = 100
        mock_play.game_id = 1
        mock_play.play_index = 1
        mock_play.created_at = datetime.now(UTC)
        mock_play.play_type = "shot"
        mock_play.description = "3-pointer"
        mock_play.raw_data = None
        mock_play.home_score = None
        mock_play.away_score = None
        mock_play.quarter = None
        mock_play.game_clock = None
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_play]
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        await poller._poll_pbp()
        mock_mgr.publish.assert_called_once()

        # Same play again — should be deduped
        mock_mgr.publish.reset_mock()
        await poller._poll_pbp()
        mock_mgr.publish.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_pbp_no_matching_game_ids(self, mock_mgr):
        mock_mgr.active_channels.return_value = {"game:abc:pbp"}  # non-int ID
        poller = DBPoller()
        await poller._poll_pbp()
        # Should not crash, just skip

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_pbp_cleans_stale_games(self, mock_mgr, mock_sf):
        mock_mgr.active_channels.return_value = {"game:1:pbp"}
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        # Pre-populate stale game
        poller._seen_pbp[999] = _LRUSet(10)
        await poller._poll_pbp()
        assert 999 not in poller._seen_pbp


# ---------------------------------------------------------------------------
# _poll_fairbet
# ---------------------------------------------------------------------------

class TestPollFairbet:
    @pytest.mark.asyncio
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_fairbet_no_subscribers_skips(self, mock_mgr):
        mock_mgr.has_subscribers.return_value = False
        poller = DBPoller()
        await poller._poll_fairbet()
        mock_mgr.publish.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_fairbet_emits_on_changes(self, mock_mgr, mock_sf):
        mock_mgr.publish = AsyncMock()
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        await poller._poll_fairbet()

        assert poller._poll_count["fairbet"] == 1
        mock_mgr.publish.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_fairbet_no_changes(self, mock_mgr, mock_sf):
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        await poller._poll_fairbet()
        mock_mgr.publish.assert_not_called()

    @pytest.mark.asyncio
    @patch("app.realtime.poller._get_session_factory")
    @patch("app.realtime.poller.realtime_manager")
    async def test_poll_fairbet_debounces(self, mock_mgr, mock_sf):
        mock_mgr.has_subscribers.return_value = True

        mock_session = AsyncMock()
        mock_sf.return_value = MagicMock(return_value=mock_session)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_result = MagicMock()
        mock_result.scalar.return_value = 1
        mock_session.execute = AsyncMock(return_value=mock_result)

        poller = DBPoller()
        poller._last_fairbet_publish = datetime.now(UTC)  # Just published

        await poller._poll_fairbet()
        # Should debounce — not publish again within the interval
        mock_mgr.publish.assert_not_called()
