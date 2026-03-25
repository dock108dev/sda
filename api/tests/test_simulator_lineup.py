"""Tests for lineup-aware MLB simulation support in simulator routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.routers.simulator_mlb import MLBSimulationRequest


class TestLineupRequest:
    """Test lineup parameter acceptance on the request model."""

    def test_accepts_lineup_fields(self):
        req = MLBSimulationRequest(
            home_team="NYY",
            away_team="LAD",
            home_lineup=["123", "456", "789"],
            away_lineup=["321", "654", "987"],
            home_starter="100",
            away_starter="200",
            starter_innings=5.0,
        )
        assert req.home_lineup == ["123", "456", "789"]
        assert req.away_lineup == ["321", "654", "987"]
        assert req.home_starter == "100"
        assert req.away_starter == "200"
        assert req.starter_innings == 5.0

    def test_backward_compatible_without_lineups(self):
        req = MLBSimulationRequest(home_team="NYY", away_team="LAD")
        assert req.home_lineup is None
        assert req.away_lineup is None
        assert req.home_starter is None
        assert req.away_starter is None
        assert req.starter_innings == 6.0

    def test_lineup_max_9(self):
        req = MLBSimulationRequest(
            home_team="NYY",
            away_team="LAD",
            home_lineup=[str(i) for i in range(9)],
            away_lineup=[str(i) for i in range(9)],
        )
        assert len(req.home_lineup) == 9


class TestBuildLineupContext:
    """Tests for the _build_lineup_context helper."""

    @pytest.mark.asyncio
    @patch("app.routers.simulator_mlb.get_pitcher_rolling_profile")
    @patch("app.routers.simulator_mlb.get_player_rolling_profile")
    async def test_builds_weight_arrays(self, mock_batter, mock_pitcher):
        from app.routers.simulator_mlb import _build_lineup_context

        mock_batter.return_value = {
            "contact_rate": 0.80,
            "whiff_rate": 0.20,
            "swing_rate": 0.48,
            "power_index": 0.15,
            "barrel_rate": 0.08,
        }
        mock_pitcher.return_value = {
            "strikeout_rate": 0.25,
            "walk_rate": 0.08,
            "contact_suppression": 0.05,
            "power_suppression": 0.10,
        }

        db = AsyncMock()
        result = await _build_lineup_context(
            home_lineup=["1", "2", "3"],
            away_lineup=["4", "5", "6"],
            home_starter="10",
            away_starter="20",
            home_team_id=1,
            away_team_id=2,
            rolling_window=30,
            starter_innings=6.0,
            db=db,
        )

        assert result is not None
        assert "home_lineup_weights" in result
        assert "away_lineup_weights" in result
        assert len(result["home_lineup_weights"]) == 9  # padded to 9
        assert len(result["away_lineup_weights"]) == 9
        assert result["starter_innings"] == 6.0
        # Each weight array should have 7 elements (PA events)
        assert len(result["home_lineup_weights"][0]) == 7

    @pytest.mark.asyncio
    async def test_returns_none_without_team_ids(self):
        from app.routers.simulator_mlb import _build_lineup_context

        db = AsyncMock()
        result = await _build_lineup_context(
            home_lineup=["1"],
            away_lineup=["2"],
            home_starter=None,
            away_starter=None,
            home_team_id=None,
            away_team_id=None,
            rolling_window=30,
            starter_innings=6.0,
            db=db,
        )
        assert result is None

    @pytest.mark.asyncio
    @patch("app.routers.simulator_mlb.get_pitcher_rolling_profile")
    @patch("app.routers.simulator_mlb.get_player_rolling_profile")
    async def test_falls_back_to_defaults_for_missing_profiles(
        self, mock_batter, mock_pitcher,
    ):
        from app.routers.simulator_mlb import _build_lineup_context

        mock_batter.return_value = None  # No batter data
        mock_pitcher.return_value = None  # No pitcher data

        db = AsyncMock()
        result = await _build_lineup_context(
            home_lineup=["1", "2", "3"],
            away_lineup=["4", "5"],
            home_starter=None,
            away_starter=None,
            home_team_id=1,
            away_team_id=2,
            rolling_window=30,
            starter_innings=6.0,
            db=db,
        )

        assert result is not None
        # Should still produce valid weight arrays using defaults
        assert len(result["home_lineup_weights"]) == 9
        assert len(result["away_lineup_weights"]) == 9
        # All weights should sum to ~1.0
        for w in result["home_lineup_weights"]:
            assert abs(sum(w) - 1.0) < 0.01
