"""Tests for golf pool scoring, ingestion sync functions, persistence, and client internals."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest


# ============================================================================
# pool_scoring.py
# ============================================================================


class TestParseRules:
    """Unit tests for _parse_rules."""

    def test_none_returns_defaults(self):
        from sports_scraper.golf.pool_scoring import _parse_rules

        result = _parse_rules(None)
        assert result["variant"] == "rvcc"
        assert result["pick_count"] == 7
        assert result["count_best"] == 5
        assert result["min_cuts_to_qualify"] == 5

    def test_empty_dict_returns_defaults(self):
        from sports_scraper.golf.pool_scoring import _parse_rules

        result = _parse_rules({})
        assert result["variant"] == "rvcc"

    def test_crestmont_variant(self):
        from sports_scraper.golf.pool_scoring import _parse_rules

        result = _parse_rules({"variant": "crestmont"})
        assert result["variant"] == "crestmont"
        assert result["pick_count"] == 6
        assert result["count_best"] == 4
        assert result["min_cuts_to_qualify"] == 4

    def test_custom_overrides(self):
        from sports_scraper.golf.pool_scoring import _parse_rules

        result = _parse_rules({"variant": "rvcc", "pick_count": 10, "count_best": 6})
        assert result["pick_count"] == 10
        assert result["count_best"] == 6

    def test_unknown_variant_falls_back_to_rvcc(self):
        from sports_scraper.golf.pool_scoring import _parse_rules

        result = _parse_rules({"variant": "CUSTOM_UNKNOWN"})
        assert result["variant"] == "custom_unknown"
        assert result["pick_count"] == 7


class TestAnyRoundsPending:
    """Unit tests for _any_rounds_pending."""

    def test_no_golfer_in_leaderboard_returns_true(self):
        from sports_scraper.golf.pool_scoring import _any_rounds_pending

        leaderboard = {}
        picks = [{"dg_id": 1}]
        assert _any_rounds_pending(leaderboard, picks) is True

    def test_active_no_r2_returns_true(self):
        from sports_scraper.golf.pool_scoring import _any_rounds_pending

        leaderboard = {1: {"status": "active", "r2": None}}
        picks = [{"dg_id": 1}]
        assert _any_rounds_pending(leaderboard, picks) is True

    def test_all_complete_returns_false(self):
        from sports_scraper.golf.pool_scoring import _any_rounds_pending

        leaderboard = {1: {"status": "active", "r2": 72}}
        picks = [{"dg_id": 1}]
        assert _any_rounds_pending(leaderboard, picks) is False

    def test_cut_player_not_pending(self):
        from sports_scraper.golf.pool_scoring import _any_rounds_pending

        leaderboard = {1: {"status": "cut", "r2": 75}}
        picks = [{"dg_id": 1}]
        assert _any_rounds_pending(leaderboard, picks) is False


class TestScoreEntry:
    """Unit tests for _score_entry."""

    def _make_entry(self, picks):
        return {
            "entry_id": 1,
            "email": "a@b.com",
            "entry_name": "Team A",
            "picks": picks,
        }

    def _make_leaderboard(self, entries):
        return {e["dg_id"]: e for e in entries}

    def _default_rules(self):
        return {
            "variant": "rvcc",
            "pick_count": 7,
            "count_best": 5,
            "min_cuts_to_qualify": 5,
        }

    def test_unknown_golfer_marked_as_dropped(self):
        from sports_scraper.golf.pool_scoring import _score_entry

        entry = self._make_entry([{"dg_id": 999, "player_name": "Unknown", "pick_slot": 1, "bucket_number": 1}])
        result = _score_entry(entry, {}, self._default_rules())
        assert result["picks"][0]["status"] == "unknown"
        assert result["picks"][0]["is_dropped"] is True
        assert result["qualification_status"] == "pending"

    def test_qualified_entry(self):
        from sports_scraper.golf.pool_scoring import _score_entry

        picks = [
            {"dg_id": i, "player_name": f"P{i}", "pick_slot": i, "bucket_number": 1}
            for i in range(1, 8)
        ]
        lb = self._make_leaderboard([
            {"dg_id": i, "player_name": f"P{i}", "status": "active",
             "position": i, "total_score": -5 + i, "thru": 18,
             "r1": 70, "r2": 70, "r3": 70, "r4": 70}
            for i in range(1, 8)
        ])
        result = _score_entry(self._make_entry(picks), lb, self._default_rules())
        assert result["qualification_status"] == "qualified"
        assert result["qualified_golfers_count"] == 7
        assert result["counted_golfers_count"] == 5
        # Best 5 should count
        counted = [p for p in result["picks"] if p["counts_toward_total"]]
        assert len(counted) == 5

    def test_not_qualified_entry(self):
        from sports_scraper.golf.pool_scoring import _score_entry

        picks = [
            {"dg_id": i, "player_name": f"P{i}", "pick_slot": i, "bucket_number": 1}
            for i in range(1, 4)
        ]
        lb = self._make_leaderboard([
            {"dg_id": i, "player_name": f"P{i}", "status": "cut",
             "position": None, "total_score": 5, "thru": 18,
             "r1": 75, "r2": 80, "r3": None, "r4": None}
            for i in range(1, 4)
        ])
        result = _score_entry(self._make_entry(picks), lb, self._default_rules())
        assert result["qualification_status"] == "not_qualified"

    def test_aggregate_score_computed(self):
        from sports_scraper.golf.pool_scoring import _score_entry

        picks = [
            {"dg_id": i, "player_name": f"P{i}", "pick_slot": i, "bucket_number": 1}
            for i in range(1, 8)
        ]
        lb = self._make_leaderboard([
            {"dg_id": i, "player_name": f"P{i}", "status": "active",
             "position": i, "total_score": -2, "thru": 18,
             "r1": 70, "r2": 70, "r3": 70, "r4": 70}
            for i in range(1, 8)
        ])
        result = _score_entry(self._make_entry(picks), lb, self._default_rules())
        assert result["aggregate_score"] == -10  # -2 * 5


class TestRankEntries:
    """Unit tests for _rank_entries."""

    def test_ranks_qualified_by_score(self):
        from sports_scraper.golf.pool_scoring import _rank_entries

        entries = [
            {"qualification_status": "qualified", "aggregate_score": -8, "rank": None, "is_tied": False},
            {"qualification_status": "qualified", "aggregate_score": -10, "rank": None, "is_tied": False},
            {"qualification_status": "qualified", "aggregate_score": -8, "rank": None, "is_tied": False},
        ]
        ranked = _rank_entries(entries)
        assert ranked[0]["aggregate_score"] == -10
        assert ranked[0]["rank"] == 1
        assert ranked[1]["rank"] == 2
        assert ranked[2]["rank"] == 2
        assert ranked[1]["is_tied"] is True
        assert ranked[2]["is_tied"] is True

    def test_pending_after_qualified(self):
        from sports_scraper.golf.pool_scoring import _rank_entries

        entries = [
            {"qualification_status": "qualified", "aggregate_score": -5, "rank": None, "is_tied": False},
            {"qualification_status": "pending", "aggregate_score": None, "rank": None, "is_tied": False},
        ]
        ranked = _rank_entries(entries)
        assert ranked[0]["rank"] == 1
        assert ranked[1]["rank"] == 2

    def test_not_qualified_gets_none_rank(self):
        from sports_scraper.golf.pool_scoring import _rank_entries

        entries = [
            {"qualification_status": "not_qualified", "aggregate_score": None, "rank": None, "is_tied": False},
        ]
        ranked = _rank_entries(entries)
        assert ranked[0]["rank"] is None


class TestScoreAllLivePools:
    """Integration-level tests for score_all_live_pools."""

    def test_no_live_pools(self):
        from sports_scraper.golf.pool_scoring import score_all_live_pools

        session = MagicMock()
        session.execute.return_value.fetchall.return_value = []

        result = score_all_live_pools(session)
        assert result == {"pools_scored": 0, "total_entries": 0}

    def test_pool_with_entries_and_leaderboard(self):
        from sports_scraper.golf.pool_scoring import score_all_live_pools

        session = MagicMock()

        # First call: _load_live_pools
        pool_rows = [(1, "CLUB1", 100, None, "live")]
        # Second call: _load_entries_and_picks -> entry rows
        entry_rows = [(10, "test@example.com", "Team X")]
        # Third call: pick rows for entry 10
        pick_rows = [
            (i, f"Player {i}", i, 1)
            for i in range(1, 8)
        ]
        # Fourth call: _load_leaderboard
        lb_rows = [
            (i, f"Player {i}", "active", i, -3 + i, 18, 70, 70, 70, 70)
            for i in range(1, 8)
        ]

        # Mock sequential execute calls
        call_results = [
            MagicMock(fetchall=MagicMock(return_value=pool_rows)),      # live pools
            MagicMock(fetchall=MagicMock(return_value=entry_rows)),      # entries
            MagicMock(fetchall=MagicMock(return_value=pick_rows)),       # picks
            MagicMock(fetchall=MagicMock(return_value=lb_rows)),         # leaderboard
        ]
        # After leaderboard, there are upsert calls that don't use fetchall
        for _ in range(20):
            call_results.append(MagicMock())

        session.execute.side_effect = call_results

        result = score_all_live_pools(session)
        assert result["pools_scored"] == 1
        assert result["total_entries"] == 1
        session.commit.assert_called_once()

    def test_pool_scoring_exception_rolls_back(self):
        from sports_scraper.golf.pool_scoring import score_all_live_pools

        session = MagicMock()
        pool_rows = [(1, "CLUB1", 100, None, "live")]

        # First call returns pools, second raises
        session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=pool_rows)),
            Exception("DB error"),
        ]

        result = score_all_live_pools(session)
        assert result["pools_scored"] == 0
        session.rollback.assert_called_once()

    def test_pool_with_no_entries_skipped(self):
        from sports_scraper.golf.pool_scoring import score_all_live_pools

        session = MagicMock()
        pool_rows = [(1, "CLUB1", 100, None, "live")]
        empty_entries = []

        session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=pool_rows)),
            MagicMock(fetchall=MagicMock(return_value=empty_entries)),
        ]

        result = score_all_live_pools(session)
        assert result["pools_scored"] == 0
        assert result["total_entries"] == 0

    def test_pool_with_no_leaderboard_skipped(self):
        from sports_scraper.golf.pool_scoring import score_all_live_pools

        session = MagicMock()
        pool_rows = [(1, "CLUB1", 100, None, "live")]
        entry_rows = [(10, "a@b.com", "Team")]
        pick_rows = [(1, "P1", 1, 1)]
        empty_lb = []

        session.execute.side_effect = [
            MagicMock(fetchall=MagicMock(return_value=pool_rows)),
            MagicMock(fetchall=MagicMock(return_value=entry_rows)),
            MagicMock(fetchall=MagicMock(return_value=pick_rows)),
            MagicMock(fetchall=MagicMock(return_value=empty_lb)),
        ]

        result = score_all_live_pools(session)
        assert result["pools_scored"] == 0


class TestUpsertEntryScore:
    """Test _upsert_entry_score calls session.execute."""

    def test_upsert_calls_execute(self):
        from sports_scraper.golf.pool_scoring import _upsert_entry_score

        session = MagicMock()
        scored = {
            "entry_id": 10,
            "rank": 1,
            "is_tied": False,
            "aggregate_score": -10,
            "qualified_golfers_count": 5,
            "counted_golfers_count": 5,
            "qualification_status": "qualified",
            "is_complete": True,
        }
        _upsert_entry_score(session, 1, scored)
        session.execute.assert_called_once()


class TestUpsertScorePlayers:
    """Test _upsert_score_players calls session.execute per pick."""

    def test_upsert_per_pick(self):
        from sports_scraper.golf.pool_scoring import _upsert_score_players

        session = MagicMock()
        picks = [
            {
                "dg_id": 1, "player_name": "P1", "pick_slot": 1,
                "status": "active", "made_cut": True,
                "counts_toward_total": True, "is_dropped": False,
            },
            {
                "dg_id": 2, "player_name": "P2", "pick_slot": 2,
                "status": "cut", "made_cut": False,
                "counts_toward_total": False, "is_dropped": True,
            },
        ]
        _upsert_score_players(session, 1, 10, picks)
        assert session.execute.call_count == 2


# ============================================================================
# persistence.py
# ============================================================================


class TestUpsertPlayers:
    """Tests for persistence.upsert_players."""

    def test_empty_list_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_players

        session = MagicMock()
        assert upsert_players(session, []) == 0
        session.execute.assert_not_called()

    def test_upserts_each_player(self):
        from sports_scraper.golf.persistence import upsert_players

        session = MagicMock()
        players = [
            {"dg_id": 1, "player_name": "Tiger Woods", "country": "USA",
             "country_code": "US", "amateur": False},
            {"dg_id": 2, "player_name": "Rory McIlroy", "country": "NIR",
             "country_code": "GB", "amateur": False},
        ]
        result = upsert_players(session, players)
        assert result == 2
        assert session.execute.call_count == 2


class TestUpsertTournament:
    """Tests for persistence.upsert_tournament."""

    def test_returns_id(self):
        from sports_scraper.golf.persistence import upsert_tournament

        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (42,)

        t = {
            "event_id": "026",
            "tour": "pga",
            "event_name": "The Masters",
            "course": "Augusta",
            "start_date": "2026-04-09",
            "end_date": "2026-04-12",
            "season": 2026,
        }
        result = upsert_tournament(session, t)
        assert result == 42
        session.execute.assert_called_once()

    def test_returns_zero_when_no_row(self):
        from sports_scraper.golf.persistence import upsert_tournament

        session = MagicMock()
        session.execute.return_value.fetchone.return_value = None
        result = upsert_tournament(session, {"event_id": "001", "tour": "pga"})
        assert result == 0


class TestUpsertLeaderboardPersistence:
    """Tests for persistence.upsert_leaderboard."""

    def test_empty_list_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_leaderboard

        session = MagicMock()
        assert upsert_leaderboard(session, 1, []) == 0

    def test_upserts_entries(self):
        from sports_scraper.golf.persistence import upsert_leaderboard

        session = MagicMock()
        entries = [
            {"dg_id": 1, "player_name": "P1", "position": 1, "total_score": -5,
             "status": "active"},
            {"dg_id": 2, "player_name": "P2", "position": 2, "total_score": -3,
             "status": "active"},
        ]
        result = upsert_leaderboard(session, 100, entries)
        assert result == 2
        assert session.execute.call_count == 2


class TestUpsertField:
    """Tests for persistence.upsert_field."""

    def test_empty_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_field

        session = MagicMock()
        assert upsert_field(session, 1, []) == 0

    def test_upserts_field_entries(self):
        from sports_scraper.golf.persistence import upsert_field

        session = MagicMock()
        entries = [{"dg_id": 1, "player_name": "P1"}]
        result = upsert_field(session, 100, entries)
        assert result == 1


class TestUpsertRounds:
    """Tests for persistence.upsert_rounds."""

    def test_empty_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_rounds

        session = MagicMock()
        assert upsert_rounds(session, 1, []) == 0

    def test_upserts_rounds(self):
        from sports_scraper.golf.persistence import upsert_rounds

        session = MagicMock()
        rounds = [{"dg_id": 1, "round_num": 1, "score": -2, "strokes": 70}]
        result = upsert_rounds(session, 100, rounds)
        assert result == 1


class TestUpsertPlayerStats:
    """Tests for persistence.upsert_player_stats."""

    def test_empty_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_player_stats

        session = MagicMock()
        assert upsert_player_stats(session, []) == 0

    def test_upserts_stats(self):
        from sports_scraper.golf.persistence import upsert_player_stats

        session = MagicMock()
        stats = [{"dg_id": 1, "sg_total": 1.5}]
        result = upsert_player_stats(session, stats)
        assert result == 1


class TestUpsertOdds:
    """Tests for persistence.upsert_odds."""

    def test_empty_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_odds

        session = MagicMock()
        assert upsert_odds(session, 1, []) == 0

    def test_upserts_odds(self):
        from sports_scraper.golf.persistence import upsert_odds

        session = MagicMock()
        odds = [{"dg_id": 1, "player_name": "P1", "book": "dk", "market": "win", "odds": 500}]
        result = upsert_odds(session, 100, odds)
        assert result == 1


class TestUpsertDfsProjections:
    """Tests for persistence.upsert_dfs_projections."""

    def test_empty_returns_zero(self):
        from sports_scraper.golf.persistence import upsert_dfs_projections

        session = MagicMock()
        assert upsert_dfs_projections(session, 1, []) == 0

    def test_upserts_projections(self):
        from sports_scraper.golf.persistence import upsert_dfs_projections

        session = MagicMock()
        projs = [{"dg_id": 1, "player_name": "P1", "site": "dk", "salary": 10000}]
        result = upsert_dfs_projections(session, 100, projs)
        assert result == 1


# ============================================================================
# ingestion.py — sync functions
# ============================================================================


class TestSyncSchedule:
    """Tests for ingestion.sync_schedule."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_schedule(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_schedule

        mock_client = MockClient.return_value
        mock_client.get_schedule.return_value = [
            SimpleNamespace(
                event_id="001", tour="pga", event_name="Test Open",
                course="Test CC", course_key="test_cc",
                start_date=date(2026, 1, 1), end_date=date(2026, 1, 4),
                season=2026, purse=10_000_000, currency="USD",
                country="USA", latitude=33.0, longitude=-84.0,
                status="scheduled",
            ),
        ]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        result = sync_schedule(tour="pga", season=2026)
        assert result["tournaments_upserted"] == 1
        assert result["tour"] == "pga"


class TestSyncPlayers:
    """Tests for ingestion.sync_players."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_players(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_players

        mock_client = MockClient.return_value
        mock_client.get_player_list.return_value = [
            SimpleNamespace(
                dg_id=1, player_name="Tiger Woods", country="USA",
                country_code="US", amateur=False,
                dk_id=100, fd_id=200, yahoo_id=300,
            ),
        ]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
        # upsert_players is called inside context manager
        with patch("sports_scraper.golf.ingestion.upsert_players", return_value=1):
            result = sync_players()

        assert result["players_upserted"] == 1


class TestSyncLeaderboard:
    """Tests for ingestion.sync_leaderboard."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_leaderboard_with_active_tournament(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_leaderboard

        mock_client = MockClient.return_value
        player = SimpleNamespace(
            dg_id=1, player_name="P1", position=1, total_score=-5,
            today_score=-3, thru=18, total_strokes=270,
            r1=68, r2=69, r3=67, r4=66,
            status="active", sg_total=2.0, sg_ott=0.5,
            sg_app=0.5, sg_arg=0.5, sg_putt=0.5,
            win_prob=0.25, top_5_prob=0.5, top_10_prob=0.7,
            make_cut_prob=0.95,
        )
        mock_client.get_live_predictions.return_value = ([player], {})
        mock_client.get_live_tournament_stats.return_value = [player]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("sports_scraper.golf.ingestion._find_active_tournament", return_value=42), \
             patch("sports_scraper.golf.ingestion.upsert_leaderboard", return_value=1):
            result = sync_leaderboard()

        assert result["leaderboard_entries_upserted"] == 1
        assert result["tournament_id"] == 42

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_leaderboard_empty(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_leaderboard

        mock_client = MockClient.return_value
        mock_client.get_live_predictions.return_value = ([], {})
        mock_client.get_live_tournament_stats.return_value = []

        result = sync_leaderboard()
        assert result["leaderboard_entries_upserted"] == 0
        assert result["tournament_id"] is None

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_leaderboard_no_active_tournament(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_leaderboard

        mock_client = MockClient.return_value
        player = SimpleNamespace(
            dg_id=1, player_name="P1", position=1, total_score=-5,
            today_score=-3, thru=18, total_strokes=270,
            r1=68, r2=69, r3=67, r4=66,
            status="active", sg_total=2.0, sg_ott=0.5,
            sg_app=0.5, sg_arg=0.5, sg_putt=0.5,
            win_prob=0.25, top_5_prob=0.5, top_10_prob=0.7,
            make_cut_prob=0.95,
        )
        mock_client.get_live_predictions.return_value = ([player], {})
        mock_client.get_live_tournament_stats.return_value = [player]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("sports_scraper.golf.ingestion._find_active_tournament", return_value=None):
            result = sync_leaderboard()

        assert result["leaderboard_entries_upserted"] == 0
        assert result["tournament_id"] is None


class TestSyncField:
    """Tests for ingestion.sync_field."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_field_empty(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_field

        MockClient.return_value.get_field_updates.return_value = []
        result = sync_field()
        assert result["field_entries_upserted"] == 0

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_field_with_data(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_field

        MockClient.return_value.get_field_updates.return_value = [
            SimpleNamespace(
                dg_id=1, player_name="P1", country="USA",
                r1_teetime="8:00", r2_teetime="12:00",
                tee_time="8:00", early_late="early",
                course="Test CC", dk_salary=10000, fd_salary=11000,
            ),
        ]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("sports_scraper.golf.ingestion._find_active_tournament", return_value=42), \
             patch("sports_scraper.golf.ingestion.upsert_field", return_value=1):
            result = sync_field()

        assert result["field_entries_upserted"] == 1
        assert result["tournament_id"] == 42


class TestSyncOdds:
    """Tests for ingestion.sync_odds."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_odds_empty(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_odds

        MockClient.return_value.get_outrights.return_value = []
        result = sync_odds()
        assert result["odds_upserted"] == 0

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_odds_with_data(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_odds

        MockClient.return_value.get_outrights.return_value = [
            SimpleNamespace(dg_id=1, player_name="P1", book="dk",
                            market="win", odds=500, implied_prob=0.1, dg_prob=0.12),
        ]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("sports_scraper.golf.ingestion._find_active_tournament", return_value=42), \
             patch("sports_scraper.golf.ingestion.upsert_odds", return_value=1):
            result = sync_odds()

        assert result["odds_upserted"] == 1


class TestSyncDfsProjections:
    """Tests for ingestion.sync_dfs_projections."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_dfs_empty(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_dfs_projections

        MockClient.return_value.get_dfs_projections.return_value = []
        result = sync_dfs_projections()
        assert result["projections_upserted"] == 0

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_dfs_with_data(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_dfs_projections

        MockClient.return_value.get_dfs_projections.return_value = [
            SimpleNamespace(dg_id=1, player_name="P1", site="dk",
                            salary=10000, projected_points=50.0,
                            projected_ownership=0.15),
        ]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("sports_scraper.golf.ingestion._find_active_tournament", return_value=42), \
             patch("sports_scraper.golf.ingestion.upsert_dfs_projections", return_value=1):
            result = sync_dfs_projections()

        assert result["projections_upserted"] == 1


class TestSyncStats:
    """Tests for ingestion.sync_stats."""

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_stats_empty(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_stats

        MockClient.return_value.get_skill_ratings.return_value = []
        result = sync_stats()
        assert result["stats_upserted"] == 0

    @patch("sports_scraper.golf.ingestion.get_session")
    @patch("sports_scraper.golf.ingestion.DataGolfClient")
    def test_sync_stats_with_data(self, MockClient, mock_get_session):
        from sports_scraper.golf.ingestion import sync_stats

        MockClient.return_value.get_skill_ratings.return_value = [
            SimpleNamespace(dg_id=1, player_name="P1",
                            sg_total=1.5, sg_ott=0.5, sg_app=0.3,
                            sg_arg=0.2, sg_putt=0.5,
                            driving_dist=300.0, driving_acc=65.0,
                            sample_size=100),
        ]

        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        with patch("sports_scraper.golf.ingestion.upsert_player_stats", return_value=1):
            result = sync_stats()

        assert result["stats_upserted"] == 1


class TestFindActiveTournament:
    """Tests for ingestion._find_active_tournament."""

    def test_in_progress_tournament(self):
        from sports_scraper.golf.ingestion import _find_active_tournament

        session = MagicMock()
        session.execute.return_value.fetchone.return_value = (42,)

        result = _find_active_tournament(session, "pga")
        assert result == 42

    def test_fallback_to_upcoming(self):
        from sports_scraper.golf.ingestion import _find_active_tournament

        session = MagicMock()
        # First call returns None (no in-progress), second returns upcoming
        session.execute.return_value.fetchone.side_effect = [None, (99,)]

        result = _find_active_tournament(session, "pga")
        assert result == 99

    def test_no_tournament_found(self):
        from sports_scraper.golf.ingestion import _find_active_tournament

        session = MagicMock()
        session.execute.return_value.fetchone.side_effect = [None, None]

        result = _find_active_tournament(session, "pga")
        assert result is None


# ============================================================================
# client.py — _get, rate limiting, error handling
# ============================================================================


class TestClientGet:
    """Tests for DataGolfClient._get internals."""

    @patch("sports_scraper.golf.client.httpx.Client")
    def test_get_raises_on_http_error(self, MockHttpClient):
        import pytest
        from sports_scraper.golf.client import DataGolfClient

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        MockHttpClient.return_value.get.return_value = mock_resp

        client = DataGolfClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="DataGolf API error 500"):
            client._get("/some-endpoint")

    @patch("sports_scraper.golf.client.httpx.Client")
    def test_get_raises_on_network_exception(self, MockHttpClient):
        import pytest
        from sports_scraper.golf.client import DataGolfClient

        MockHttpClient.return_value.get.side_effect = Exception("connection failed")

        client = DataGolfClient(api_key="test-key")
        with pytest.raises(Exception, match="connection failed"):
            client._get("/some-endpoint")

    @patch("sports_scraper.golf.client.httpx.Client")
    def test_get_returns_json_on_success(self, MockHttpClient):
        from sports_scraper.golf.client import DataGolfClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": [1, 2, 3]}
        MockHttpClient.return_value.get.return_value = mock_resp

        client = DataGolfClient(api_key="test-key")
        result = client._get("/some-endpoint")
        assert result == {"data": [1, 2, 3]}

    @patch("sports_scraper.golf.client.time")
    @patch("sports_scraper.golf.client.httpx.Client")
    def test_rate_limiting_sleeps_when_too_fast(self, MockHttpClient, mock_time):
        from sports_scraper.golf.client import DataGolfClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}
        MockHttpClient.return_value.get.return_value = mock_resp

        # monotonic returns values showing requests are too close together
        mock_time.monotonic.side_effect = [0.5, 1.0]  # now=0.5, after_request=1.0
        mock_time.sleep = MagicMock()

        client = DataGolfClient(api_key="test-key")
        client._last_request_at = 0.0  # previous request at t=0

        client._get("/test")

        # elapsed = 0.5 - 0.0 = 0.5, which is < 1.4, so should sleep 0.9
        mock_time.sleep.assert_called_once_with(pytest.approx(0.9, abs=0.01))

    @patch("sports_scraper.golf.client.httpx.Client")
    def test_get_non_200_with_empty_body(self, MockHttpClient):
        import pytest
        from sports_scraper.golf.client import DataGolfClient

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = ""
        MockHttpClient.return_value.get.return_value = mock_resp

        client = DataGolfClient(api_key="test-key")
        with pytest.raises(RuntimeError, match="DataGolf API error 429"):
            client._get("/rate-limited")
