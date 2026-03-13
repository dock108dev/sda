"""Tests for MLBPADatasetBuilder and _pitcher_stats_to_metrics."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.analytics.datasets.mlb_pa_dataset import (
    MLBPADatasetBuilder,
    _pitcher_stats_to_metrics,
)


# ---------------------------------------------------------------------------
# _pitcher_stats_to_metrics
# ---------------------------------------------------------------------------


class TestPitcherStatsToMetrics:
    """Unit tests for the _pitcher_stats_to_metrics helper."""

    def _make_stats(self, **overrides):
        defaults = dict(
            batters_faced=20,
            innings_pitched=6.0,
            strikeouts=5,
            walks=2,
            home_runs_allowed=1,
            hits=6,
            pitches_thrown=90,
            zone_swings=20,
            zone_contact=15,
            outside_swings=10,
            outside_contact=5,
            outside_pitches=30,
            balls_in_play=12,
            total_exit_velo_against=1056.0,
            hard_hit_against=4,
            barrel_against=2,
        )
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_basic_rates(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert abs(m["k_rate"] - 5 / 20) < 0.001
        assert abs(m["bb_rate"] - 2 / 20) < 0.001
        assert abs(m["hr_rate"] - 1 / 20) < 0.001
        assert m["innings_pitched"] == 6.0
        assert m["batters_faced"] == 20.0

    def test_whiff_rate(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        total_swings = 20 + 10
        total_contact = 15 + 5
        expected = 1.0 - (total_contact / total_swings)
        assert abs(m["whiff_rate"] - expected) < 0.001

    def test_zone_contact_pct(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert abs(m["z_contact_pct"] - 15 / 20) < 0.001

    def test_chase_rate(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert abs(m["chase_rate"] - 10 / 30) < 0.001

    def test_avg_exit_velo_against(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert abs(m["avg_exit_velo_against"] - 1056.0 / 12) < 0.001

    def test_hard_hit_pct_against(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert abs(m["hard_hit_pct_against"] - 4 / 12) < 0.001

    def test_barrel_pct_against(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert abs(m["barrel_pct_against"] - 2 / 12) < 0.001

    def test_zero_batters_faced_uses_defaults(self):
        stats = self._make_stats(batters_faced=0)
        m = _pitcher_stats_to_metrics(stats)
        assert m["k_rate"] == 0.22
        assert m["bb_rate"] == 0.08
        assert m["hr_rate"] == 0.03

    def test_zero_swings_uses_defaults(self):
        stats = self._make_stats(zone_swings=0, outside_swings=0)
        m = _pitcher_stats_to_metrics(stats)
        assert m["whiff_rate"] == 0.23

    def test_zero_bip_uses_defaults(self):
        stats = self._make_stats(balls_in_play=0)
        m = _pitcher_stats_to_metrics(stats)
        assert m["avg_exit_velo_against"] == 88.0
        assert m["hard_hit_pct_against"] == 0.35
        assert m["barrel_pct_against"] == 0.07

    def test_suppression_metrics_present(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert "contact_suppression" in m
        assert "power_suppression" in m
        assert "strikeout_rate" in m
        assert "walk_rate" in m

    def test_suppression_clamped(self):
        stats = self._make_stats()
        m = _pitcher_stats_to_metrics(stats)
        assert -0.15 <= m["contact_suppression"] <= 0.30
        assert -0.30 <= m["power_suppression"] <= 0.50


# ---------------------------------------------------------------------------
# MLBPADatasetBuilder
# ---------------------------------------------------------------------------


class TestMLBPADatasetBuilder:
    """Tests for the dataset builder with mocked DB."""

    @pytest.mark.asyncio
    async def test_build_returns_empty_for_no_games(self):
        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        db.execute.return_value = result_mock

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(date_start="2025-07-01", date_end="2025-10-01")
        assert rows == []

    @pytest.mark.asyncio
    async def test_build_extracts_pas_from_plays(self):
        """Builder extracts PAs from play data and labels them."""
        db = AsyncMock()

        # Mock game
        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20
        game.status = "final"

        # Mock plays with PA events
        play1 = MagicMock()
        play1.game_id = 1
        play1.play_index = 0
        play1.player_id = "100"
        play1.quarter = 1
        play1.raw_data = {
            "event": "Strikeout",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100, "fullName": "Batter A"},
                "pitcher": {"id": 200, "fullName": "Pitcher B"},
                "batSide": {"code": "R"},
                "pitchHand": {"code": "R"},
            },
        }

        play2 = MagicMock()
        play2.game_id = 1
        play2.play_index = 1
        play2.player_id = "101"
        play2.quarter = 1
        play2.raw_data = {
            "event": "Single",
            "about": {"inning": 1, "halfInning": "top", "outs": 1},
            "matchup": {
                "batter": {"id": 101},
                "pitcher": {"id": 200},
            },
        }

        # Non-PA play (stolen base)
        play3 = MagicMock()
        play3.game_id = 1
        play3.play_index = 2
        play3.player_id = "101"
        play3.quarter = 1
        play3.raw_data = {"event": "Stolen Base"}

        # Set up execute mock to return games first, then plays
        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Games query
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                # Plays query
                result.scalars.return_value.all.return_value = [play1, play2, play3]
            else:
                result.scalars.return_value.all.return_value = []
                result.all.return_value = []
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(include_profiles=False)

        assert len(rows) == 2
        assert rows[0]["outcome"] == "strikeout"
        assert rows[0]["batter_external_ref"] == "100"
        assert rows[0]["pitcher_external_ref"] == "200"
        assert rows[0]["inning"] == 1
        assert rows[0]["half"] == "top"
        assert rows[0]["batter_hand"] == "R"

        assert rows[1]["outcome"] == "single"
        assert rows[1]["batter_external_ref"] == "101"

    def test_build_player_profile_filters_before_date(self):
        """Point-in-time safety: only games before the target date."""
        builder = MLBPADatasetBuilder(AsyncMock())

        history = {
            "player1": [
                ("2025-07-01", MagicMock()),
                ("2025-07-10", MagicMock()),
                ("2025-07-20", MagicMock()),  # should be excluded
            ]
        }

        # Target game is on 2025-07-15 — only 2 qualify but need 5
        result = builder._build_player_profile(
            "player1", history, "2025-07-15", window=30, min_games=5,
        )
        assert result is None

    def test_build_player_profile_empty_history(self):
        builder = MLBPADatasetBuilder(AsyncMock())
        result = builder._build_player_profile(
            "unknown", {}, "2025-08-01", 30, 3,
        )
        assert result is None

    def test_build_pitcher_profile_insufficient_games(self):
        builder = MLBPADatasetBuilder(AsyncMock())
        history = {"p1": [("2025-07-01", MagicMock())]}
        result = builder._build_pitcher_profile("p1", history, "2025-08-01", 30, 3)
        assert result is None

    def test_build_pitcher_profile_empty_history(self):
        builder = MLBPADatasetBuilder(AsyncMock())
        result = builder._build_pitcher_profile("unknown", {}, "2025-08-01", 30, 3)
        assert result is None

    def test_build_player_profile_with_sufficient_games(self):
        """_build_player_profile returns aggregated metrics when enough prior games."""
        builder = MLBPADatasetBuilder(AsyncMock())

        def _make_batter_stats():
            return SimpleNamespace(
                total_pitches=80, zone_pitches=40, zone_swings=20,
                zone_contact=15, outside_pitches=40, outside_swings=10,
                outside_contact=5, z_swing_pct=0.50, o_swing_pct=0.25,
                z_contact_pct=0.75, o_contact_pct=0.50, balls_in_play=10,
                hard_hit_count=3, barrel_count=1, avg_exit_velo=89.0,
                hard_hit_pct=0.30, barrel_pct=0.10,
            )

        history = {
            "b1": [
                (f"2025-07-{str(d).zfill(2)}", _make_batter_stats())
                for d in range(1, 11)  # 10 games before target
            ]
        }
        result = builder._build_player_profile("b1", history, "2025-08-01", 30, 5)
        assert result is not None
        assert isinstance(result, dict)
        # Should contain metrics produced by stats_to_metrics
        assert "contact_rate" in result or "total_pitches" in result

    def test_build_pitcher_profile_with_sufficient_games(self):
        """_build_pitcher_profile returns aggregated metrics when enough prior games."""
        builder = MLBPADatasetBuilder(AsyncMock())

        def _make_pitcher_stats():
            return SimpleNamespace(
                batters_faced=20, innings_pitched=6.0, strikeouts=5,
                walks=2, home_runs_allowed=1, hits=6, pitches_thrown=90,
                zone_swings=20, zone_contact=15, outside_swings=10,
                outside_contact=5, outside_pitches=30, balls_in_play=12,
                total_exit_velo_against=1056.0, hard_hit_against=4,
                barrel_against=2,
            )

        history = {
            "p1": [
                (f"2025-07-{str(d).zfill(2)}", _make_pitcher_stats())
                for d in range(1, 11)
            ]
        }
        result = builder._build_pitcher_profile("p1", history, "2025-08-01", 30, 3)
        assert result is not None
        assert isinstance(result, dict)
        assert "k_rate" in result
        assert "whiff_rate" in result
        assert "contact_suppression" in result

    def test_build_player_profile_window_limit(self):
        """_build_player_profile respects rolling window parameter."""
        builder = MLBPADatasetBuilder(AsyncMock())

        def _make_batter_stats():
            return SimpleNamespace(
                total_pitches=80, zone_pitches=40, zone_swings=20,
                zone_contact=15, outside_pitches=40, outside_swings=10,
                outside_contact=5, z_swing_pct=0.50, o_swing_pct=0.25,
                z_contact_pct=0.75, o_contact_pct=0.50, balls_in_play=10,
                hard_hit_count=3, barrel_count=1, avg_exit_velo=89.0,
                hard_hit_pct=0.30, barrel_pct=0.10,
            )

        # 40 games but window=5 should only use last 5
        history = {
            "b1": [
                (f"2025-06-{str(d).zfill(2)}", _make_batter_stats())
                for d in range(1, 30)
            ] + [
                (f"2025-07-{str(d).zfill(2)}", _make_batter_stats())
                for d in range(1, 12)
            ]
        }
        result = builder._build_player_profile("b1", history, "2025-08-01", 5, 3)
        assert result is not None

    @pytest.mark.asyncio
    async def test_build_with_profiles_skips_insufficient_history(self):
        """build() with include_profiles=True skips PAs lacking profile data."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Single",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            else:
                # Profile queries return empty results
                result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(
            include_profiles=True, min_batter_games=5, min_pitcher_games=3,
        )
        # No profile data -> all PAs skipped
        assert rows == []

    @pytest.mark.asyncio
    async def test_build_with_profiles_includes_profiles_in_row(self):
        """build() with include_profiles=True adds batter_profile and pitcher_profile."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Home Run",
            "about": {"inning": 3, "halfInning": "bottom", "outs": 1},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
                "batSide": {"code": "L"},
                "pitchHand": {"code": "R"},
            },
        }

        def _make_batter_stats():
            return SimpleNamespace(
                total_pitches=80, zone_pitches=40, zone_swings=20,
                zone_contact=15, outside_pitches=40, outside_swings=10,
                outside_contact=5, z_swing_pct=0.50, o_swing_pct=0.25,
                z_contact_pct=0.75, o_contact_pct=0.50, balls_in_play=10,
                hard_hit_count=3, barrel_count=1, avg_exit_velo=89.0,
                hard_hit_pct=0.30, barrel_pct=0.10,
                player_external_ref="100",
            )

        def _make_pitcher_stats():
            return SimpleNamespace(
                batters_faced=20, innings_pitched=6.0, strikeouts=5,
                walks=2, home_runs_allowed=1, hits=6, pitches_thrown=90,
                zone_swings=20, zone_contact=15, outside_swings=10,
                outside_contact=5, outside_pitches=30, balls_in_play=12,
                total_exit_velo_against=1056.0, hard_hit_against=4,
                barrel_against=2, player_external_ref="200",
            )

        # Build history rows: (stats_row, game_date) tuples for profile queries
        batter_rows = [
            (SimpleNamespace(
                player_external_ref="100",
                **{k: v for k, v in vars(_make_batter_stats()).items()
                   if k != "player_external_ref"}
            ), f"2025-07-{str(d).zfill(2)}")
            for d in range(1, 11)
        ]
        pitcher_rows = [
            (SimpleNamespace(
                player_external_ref="200",
                **{k: v for k, v in vars(_make_pitcher_stats()).items()
                   if k != "player_external_ref"}
            ), f"2025-07-{str(d).zfill(2)}")
            for d in range(1, 11)
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Games query
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                # Plays query
                result.scalars.return_value.all.return_value = [play]
            elif call_count == 3:
                # Batter history query
                result.__iter__ = lambda s: iter(batter_rows)
            elif call_count == 4:
                # Pitcher history query
                result.__iter__ = lambda s: iter(pitcher_rows)
            elif call_count == 5:
                # Team history query
                result.__iter__ = lambda s: iter([])
            else:
                result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(
            include_profiles=True,
            min_batter_games=5,
            min_pitcher_games=3,
        )
        assert len(rows) == 1
        assert "batter_profile" in rows[0]
        assert "pitcher_profile" in rows[0]
        assert "metrics" in rows[0]["batter_profile"]
        assert "metrics" in rows[0]["pitcher_profile"]
        assert rows[0]["outcome"] == "home_run"
        assert rows[0]["half"] == "bottom"
        assert rows[0]["batter_hand"] == "L"

    @pytest.mark.asyncio
    async def test_build_pitcher_fallback_to_team_profile(self):
        """When pitcher has no profile, falls back to team history."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Double",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        def _make_batter_stats():
            return SimpleNamespace(
                total_pitches=80, zone_pitches=40, zone_swings=20,
                zone_contact=15, outside_pitches=40, outside_swings=10,
                outside_contact=5, z_swing_pct=0.50, o_swing_pct=0.25,
                z_contact_pct=0.75, o_contact_pct=0.50, balls_in_play=10,
                hard_hit_count=3, barrel_count=1, avg_exit_velo=89.0,
                hard_hit_pct=0.30, barrel_pct=0.10,
                player_external_ref="100",
            )

        batter_rows = [
            (SimpleNamespace(
                player_external_ref="100",
                **{k: v for k, v in vars(_make_batter_stats()).items()
                   if k != "player_external_ref"}
            ), f"2025-07-{str(d).zfill(2)}")
            for d in range(1, 11)
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            elif call_count == 3:
                # Batter history
                result.__iter__ = lambda s: iter(batter_rows)
            elif call_count == 4:
                # Pitcher history - empty (no data for pitcher 200)
                result.__iter__ = lambda s: iter([])
            elif call_count == 5:
                # Team history - also empty so fallback also returns None
                result.__iter__ = lambda s: iter([])
            else:
                result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(
            include_profiles=True, min_batter_games=5, min_pitcher_games=3,
        )
        # Pitcher profile is None, team fallback also None -> skipped
        assert rows == []

    @pytest.mark.asyncio
    async def test_build_with_fielding(self):
        """build() with include_fielding=True adds team_fielding to rows."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Groundout",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        fielding_row = SimpleNamespace(
            team_id=10, avg_oaa=2.5, avg_drs=3.0, avg_def_value=1.5,
            player_count=9,
        )

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Games query
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                # Plays query
                result.scalars.return_value.all.return_value = [play]
            elif call_count == 3:
                # Fielding query
                result.__iter__ = lambda s: iter([fielding_row])
            else:
                result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(
            include_profiles=False, include_fielding=True,
        )
        assert len(rows) == 1
        assert "team_fielding" in rows[0]
        assert rows[0]["team_fielding"]["team_oaa"] == 2.5
        assert rows[0]["team_fielding"]["fielding_player_count"] == 9

    @pytest.mark.asyncio
    async def test_build_skips_missing_batter_or_pitcher(self):
        """PAs with empty batter or pitcher IDs are skipped."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        # Play with no batter/pitcher IDs
        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = None
        play.quarter = 1
        play.raw_data = {
            "event": "Single",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {},  # No batter or pitcher
        }

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            else:
                result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(include_profiles=False)
        assert rows == []

    @pytest.mark.asyncio
    async def test_build_event_falls_back_to_event_type(self):
        """When event key is empty, falls back to result.eventType."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            # No top-level "event"
            "result": {"eventType": "Strikeout"},
            "about": {"inning": 2, "halfInning": "bottom", "outs": 2},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            else:
                result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(include_profiles=False)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "strikeout"

    @pytest.mark.asyncio
    async def test_load_profile_histories(self):
        """_load_profile_histories returns batter, pitcher, and team dicts."""
        db = AsyncMock()

        batter_stat = SimpleNamespace(player_external_ref="100")
        pitcher_stat = SimpleNamespace(player_external_ref="200")
        team_stat = SimpleNamespace(team_id=10)

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Batter query
                result.__iter__ = lambda s: iter([(batter_stat, "2025-07-01")])
            elif call_count == 2:
                # Pitcher query
                result.__iter__ = lambda s: iter([(pitcher_stat, "2025-07-01")])
            elif call_count == 3:
                # Team query
                result.__iter__ = lambda s: iter([(team_stat, "2025-07-01")])
            else:
                result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        batter_h, pitcher_h, team_h = await builder._load_profile_histories(
            [1], None, 30,
        )
        assert "100" in batter_h
        assert len(batter_h["100"]) == 1
        assert "200" in pitcher_h
        assert 10 in team_h

    @pytest.mark.asyncio
    async def test_load_profile_histories_with_dt_end(self):
        """_load_profile_histories applies dt_end filter."""
        db = AsyncMock()

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        from datetime import UTC, datetime
        dt_end = datetime(2025, 8, 1, tzinfo=UTC)

        builder = MLBPADatasetBuilder(db)
        batter_h, pitcher_h, team_h = await builder._load_profile_histories(
            [1], dt_end, 30,
        )
        assert batter_h == {}
        assert pitcher_h == {}
        assert team_h == {}
        # All 3 queries should have executed
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_load_team_fielding(self):
        """_load_team_fielding returns team fielding aggregates."""
        db = AsyncMock()

        fielding_row = SimpleNamespace(
            team_id=10, avg_oaa=2.5, avg_drs=3.0, avg_def_value=1.5,
            player_count=9,
        )

        async def mock_execute(stmt):
            result = MagicMock()
            result.__iter__ = lambda s: iter([fielding_row])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        fielding = await builder._load_team_fielding([1])
        assert 10 in fielding
        assert fielding[10]["team_oaa"] == 2.5
        assert fielding[10]["team_drs"] == 3.0
        assert fielding[10]["team_defensive_value"] == 1.5
        assert fielding[10]["fielding_player_count"] == 9

    @pytest.mark.asyncio
    async def test_load_team_fielding_empty(self):
        """_load_team_fielding returns empty dict when no data."""
        db = AsyncMock()

        async def mock_execute(stmt):
            result = MagicMock()
            result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        fielding = await builder._load_team_fielding([1])
        assert fielding == {}

    @pytest.mark.asyncio
    async def test_build_pitcher_fallback_to_team_profile_succeeds(self):
        """When pitcher has no individual profile, team fallback provides it."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Single",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        def _make_batter_stats():
            return SimpleNamespace(
                total_pitches=80, zone_pitches=40, zone_swings=20,
                zone_contact=15, outside_pitches=40, outside_swings=10,
                outside_contact=5, z_swing_pct=0.50, o_swing_pct=0.25,
                z_contact_pct=0.75, o_contact_pct=0.50, balls_in_play=10,
                hard_hit_count=3, barrel_count=1, avg_exit_velo=89.0,
                hard_hit_pct=0.30, barrel_pct=0.10,
                player_external_ref="100",
            )

        def _make_team_stats():
            """Team stats compatible with stats_to_metrics."""
            return SimpleNamespace(
                total_pitches=80, zone_pitches=40, zone_swings=20,
                zone_contact=15, outside_pitches=40, outside_swings=10,
                outside_contact=5, z_swing_pct=0.50, o_swing_pct=0.25,
                z_contact_pct=0.75, o_contact_pct=0.50, balls_in_play=10,
                hard_hit_count=3, barrel_count=1, avg_exit_velo=89.0,
                hard_hit_pct=0.30, barrel_pct=0.10,
                team_id=10,
            )

        batter_rows = [
            (SimpleNamespace(
                player_external_ref="100",
                **{k: v for k, v in vars(_make_batter_stats()).items()
                   if k != "player_external_ref"}
            ), f"2025-07-{str(d).zfill(2)}")
            for d in range(1, 11)
        ]

        # Team history for fielding_team_id=10 (home team, since top inning)
        team_rows = [
            (SimpleNamespace(
                team_id=10,
                **{k: v for k, v in vars(_make_team_stats()).items()
                   if k != "team_id"}
            ), f"2025-07-{str(d).zfill(2)}")
            for d in range(1, 11)
        ]

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            elif call_count == 3:
                # Batter history
                result.__iter__ = lambda s: iter(batter_rows)
            elif call_count == 4:
                # Pitcher history - empty
                result.__iter__ = lambda s: iter([])
            elif call_count == 5:
                # Team history - has data for team 10
                result.__iter__ = lambda s: iter(team_rows)
            else:
                result.__iter__ = lambda s: iter([])
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(
            include_profiles=True, min_batter_games=5, min_pitcher_games=3,
        )
        # Pitcher fallback to team profile should succeed
        assert len(rows) == 1
        assert "pitcher_profile" in rows[0]
        assert "batter_profile" in rows[0]

    @pytest.mark.asyncio
    async def test_build_no_date_filters(self):
        """build() works without date_start and date_end."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        play = MagicMock()
        play.game_id = 1
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Walk",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            else:
                result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(include_profiles=False)
        assert len(rows) == 1
        assert rows[0]["outcome"] == "walk_or_hbp"

    @pytest.mark.asyncio
    async def test_build_game_not_in_map_skipped(self):
        """Plays referencing a game not in game_map are skipped (line 141)."""
        db = AsyncMock()

        game = MagicMock()
        game.id = 1
        game.game_date = "2025-08-15"
        game.season = 2025
        game.home_team_id = 10
        game.away_team_id = 20

        # Play references game_id=999 which is not in the game list
        play = MagicMock()
        play.game_id = 999
        play.play_index = 0
        play.player_id = "100"
        play.quarter = 1
        play.raw_data = {
            "event": "Single",
            "about": {"inning": 1, "halfInning": "top", "outs": 0},
            "matchup": {
                "batter": {"id": 100},
                "pitcher": {"id": 200},
            },
        }

        call_count = 0

        async def mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalars.return_value.all.return_value = [game]
            elif call_count == 2:
                result.scalars.return_value.all.return_value = [play]
            else:
                result.scalars.return_value.all.return_value = []
            return result

        db.execute = mock_execute

        builder = MLBPADatasetBuilder(db)
        rows = await builder.build(include_profiles=False)
        assert rows == []
