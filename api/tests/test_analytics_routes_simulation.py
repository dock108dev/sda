"""Route-level tests for simulation, matchup, roster, and lineup endpoints.

Covers uncovered lines in analytics_routes.py:
- POST /simulate (team-level and lineup-level flows)
- GET /matchup (comparison logic)
- GET /mlb-roster
- Helper functions: _regress_pitcher_profile, _pitching_metrics_from_profile
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.api.analytics_routes import (
    _pitching_metrics_from_profile,
    _regress_pitcher_profile,
    router,
)
from app.analytics.services.profile_service import ProfileResult
from app.db import get_db


def _make_client(mock_db=None):
    """Create a TestClient with mocked DB dependency."""
    if mock_db is None:
        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        result_mock.scalar_one_or_none.return_value = None
        result_mock.scalar.return_value = 0
        result_mock.all.return_value = []
        mock_db.execute.return_value = result_mock
        mock_db.get.return_value = None

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app), mock_db


def _fake_profile(overrides=None):
    """Return a realistic team profile dict."""
    base = {
        "contact_rate": 0.77,
        "power_index": 0.18,
        "barrel_rate": 0.07,
        "whiff_rate": 0.23,
        "hard_hit_rate": 0.35,
        "plate_discipline_index": 0.52,
        "avg_exit_velo": 88.5,
    }
    if overrides:
        base.update(overrides)
    return base


def _fake_profile_result(metrics=None, games_used=30):
    """Build a ProfileResult for mocking."""
    m = metrics or _fake_profile()
    return ProfileResult(
        metrics=m,
        games_used=games_used,
        date_range=("2025-06-01", "2025-07-01"),
        season_breakdown={2025: games_used},
    )


# ---------------------------------------------------------------------------
# Helper function tests (pure, no DB)
# ---------------------------------------------------------------------------


class TestRegressPitcherProfile:
    def test_starter_uses_actual_profile(self):
        profile = {"strikeout_rate": 0.28, "walk_rate": 0.06}
        result = _regress_pitcher_profile(profile, avg_ip=6.0)
        assert result is profile  # no regression

    def test_none_avg_ip_uses_actual_profile(self):
        profile = {"strikeout_rate": 0.28}
        result = _regress_pitcher_profile(profile, avg_ip=None)
        assert result is profile

    def test_reliever_gets_regressed(self):
        profile = {"strikeout_rate": 0.35, "walk_rate": 0.05}
        result = _regress_pitcher_profile(profile, avg_ip=1.0)
        # blend = 1.0 / 5.0 = 0.2; heavily regressed toward league avg
        assert result is not profile
        assert result["strikeout_rate"] < profile["strikeout_rate"]

    def test_low_ip_floors_at_ten_percent(self):
        profile = {"strikeout_rate": 0.35}
        result = _regress_pitcher_profile(profile, avg_ip=0.1)
        # blend = max(0.1 / 5.0, 0.1) = 0.1
        expected = round(0.22 + 0.1 * (0.35 - 0.22), 4)
        assert result["strikeout_rate"] == expected


class TestPitchingMetricsFromProfile:
    def test_returns_none_for_empty_profile(self):
        assert _pitching_metrics_from_profile(None) is None
        assert _pitching_metrics_from_profile({}) is None

    def test_returns_none_when_no_whiff_or_contact(self):
        assert _pitching_metrics_from_profile({"barrel_rate": 0.07}) is None

    def test_returns_metrics_for_valid_profile(self):
        profile = _fake_profile()
        result = _pitching_metrics_from_profile(profile)
        assert result is not None
        assert "strikeout_rate" in result
        assert "walk_rate" in result
        assert "contact_suppression" in result
        assert "power_suppression" in result
        # Walk rate should be clamped between 0.04 and 0.12
        assert 0.04 <= result["walk_rate"] <= 0.12

    def test_high_whiff_team_gets_higher_k_rate(self):
        high_whiff = _fake_profile({"whiff_rate": 0.30})
        low_whiff = _fake_profile({"whiff_rate": 0.18})
        high_result = _pitching_metrics_from_profile(high_whiff)
        low_result = _pitching_metrics_from_profile(low_whiff)
        assert high_result["strikeout_rate"] > low_result["strikeout_rate"]


# ---------------------------------------------------------------------------
# POST /simulate — team-level flow (lines 244-297, 314-360)
# ---------------------------------------------------------------------------


class TestPostSimulateTeamLevel:
    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_simulate_with_profiles_rule_based(
        self, mock_service, mock_get_profile, mock_predict,
    ):
        """Full simulation with team profiles, rule_based mode."""
        home_pr = _fake_profile_result(_fake_profile({"contact_rate": 0.80}))
        away_pr = _fake_profile_result(_fake_profile({"contact_rate": 0.74}))

        async def profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            return home_pr if team == "NYY" else away_pr

        mock_get_profile.side_effect = profile_side
        mock_predict.return_value = 0.58  # model prediction

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.55,
            "probability_source": "rule_based",
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
            "seed": 42,
            "probability_mode": "rule_based",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["home_team"] == "NYY"
        assert data["away_team"] == "BOS"
        # Profile meta should be present
        assert data["profile_meta"]["has_profiles"] is True
        assert data["profile_meta"]["rolling_window"] == 30
        assert "profile_pa_probabilities" in data["profile_meta"]
        # Model prediction surfaced
        assert data["model_home_win_probability"] == 0.58
        assert data["profile_meta"]["model_prediction_source"] == "game_model"
        # Data freshness
        assert "data_freshness" in data["profile_meta"]
        assert data["profile_meta"]["data_freshness"]["home"]["games_used"] == 30
        # PA probabilities surfaced for transparency
        assert "home_pa_probabilities" in data
        # Predictions block
        assert "predictions" in data
        assert "monte_carlo" in data["predictions"]
        assert "game_model" in data["predictions"]

    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_simulate_ml_mode_does_not_prepopulate_pa(
        self, mock_service, mock_get_profile, mock_predict,
    ):
        """In ml mode, profile PA probs should NOT be set into game_context."""
        home_pr = _fake_profile_result()
        away_pr = _fake_profile_result()

        async def profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            return home_pr if team == "NYY" else away_pr

        mock_get_profile.side_effect = profile_side
        mock_predict.return_value = None

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.52,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
            "probability_mode": "ml",
        })
        assert resp.status_code == 200
        # ml mode should NOT have home_pa_source = team_profile
        data = resp.json()
        pm = data.get("profile_meta", {})
        assert pm.get("home_pa_source") is None or pm.get("home_pa_source") != "team_profile"

    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_simulate_with_custom_probabilities(self, mock_service, mock_get_profile):
        """Custom home/away probabilities override profile-derived ones."""
        mock_get_profile.return_value = None  # no profiles

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.60,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
            "home_probabilities": {"strikeout_probability": 0.20},
            "away_probabilities": {"strikeout_probability": 0.25},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["home_win_probability"] == 0.60

    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_simulate_missing_profiles(self, mock_service, mock_get_profile):
        """When one profile is missing, has_profiles=False."""
        async def profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            if team == "NYY":
                return _fake_profile_result()
            return None

        mock_get_profile.side_effect = profile_side
        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.50,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
        })
        assert resp.status_code == 200
        data = resp.json()
        pm = data.get("profile_meta", {})
        assert pm.get("has_profiles") is False
        assert pm.get("home_found") is True
        assert pm.get("away_found") is False

    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_simulate_diagnostics_surfaced(
        self, mock_service, mock_get_profile, mock_predict,
    ):
        """_diagnostics in result gets surfaced as simulation_info."""
        mock_get_profile.return_value = None

        diag_mock = MagicMock()
        diag_mock.to_dict.return_value = {"executed_mode": "rule_based", "total_innings": 9}

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.55,
            "_diagnostics": diag_mock,
        }
        mock_predict.return_value = None

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "iterations": 500,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "simulation_info" in data
        assert data["simulation_info"]["executed_mode"] == "rule_based"
        # _diagnostics internal key should be removed
        assert "_diagnostics" not in data

    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_simulate_no_model_prediction(
        self, mock_service, mock_get_profile, mock_predict,
    ):
        """When model prediction is None, predictions block has no game_model."""
        home_pr = _fake_profile_result()
        away_pr = _fake_profile_result()

        async def profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            return home_pr if team == "NYY" else away_pr

        mock_get_profile.side_effect = profile_side
        mock_predict.return_value = None

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.50,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "game_model" not in data["predictions"]
        assert "model_home_win_probability" not in data


# ---------------------------------------------------------------------------
# POST /simulate — lineup-level flow (lines 476-640)
# ---------------------------------------------------------------------------


class TestPostSimulateLineupLevel:
    def _lineup(self, n=9):
        return [{"external_ref": f"player_{i}", "name": f"Player {i}"} for i in range(n)]

    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api._simulation_helpers.get_player_rolling_profile")
    @patch("app.analytics.api._simulation_helpers.get_pitcher_rolling_profile")
    @patch("app.analytics.api._simulation_helpers.get_team_info")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_lineup_simulation_full_flow(
        self, mock_service, mock_team_profile, mock_team_info,
        mock_pitcher_profile, mock_player_profile, mock_predict,
    ):
        """Full lineup simulation with starters and batters resolved."""
        home_pr = _fake_profile_result()
        away_pr = _fake_profile_result()

        async def team_profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            return home_pr if team == "NYY" else away_pr

        mock_team_profile.side_effect = team_profile_side

        async def team_info_side(team, *, db):
            if team == "NYY":
                return {"id": 1, "name": "New York Yankees"}
            return {"id": 2, "name": "Boston Red Sox"}

        mock_team_info.side_effect = team_info_side

        # Pitcher profiles
        async def pitcher_side(ref, team_id, *, rolling_window, exclude_playoffs, db):
            return {"strikeout_rate": 0.25, "walk_rate": 0.07,
                    "contact_suppression": 0.02, "power_suppression": 0.01}

        mock_pitcher_profile.side_effect = pitcher_side

        # Batter profiles
        async def player_side(ref, team_id, *, rolling_window, exclude_playoffs, db):
            return _fake_profile()

        mock_player_profile.side_effect = player_side
        mock_predict.return_value = None

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.54,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
            "seed": 42,
            "home_lineup": self._lineup(),
            "away_lineup": self._lineup(),
            "home_starter": {"external_ref": "sp_home", "name": "Home SP", "avg_ip": 6.0},
            "away_starter": {"external_ref": "sp_away", "name": "Away SP", "avg_ip": 2.0},
            "starter_innings": 6.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        pm = data.get("profile_meta", {})
        assert pm.get("lineup_mode", {}).get("enabled") is True
        assert pm["home_pa_source"] == "lineup_batter_vs_pitcher"
        assert pm["away_pa_source"] == "lineup_batter_vs_pitcher"
        # Pitcher analytics surfaced
        assert pm["home_pitcher"]["name"] == "Home SP"
        assert pm["away_pitcher"]["name"] == "Away SP"
        # Away SP has avg_ip=2.0 < 5.0 → regressed
        assert pm["away_pitcher"]["is_regressed"] is True
        assert pm["home_pitcher"]["is_regressed"] is False
        # Bullpen info
        assert "home_bullpen" in pm
        assert "away_bullpen" in pm
        # Service should have been called with use_lineup=True
        call_kwargs = mock_service.run_full_simulation.call_args
        assert call_kwargs.kwargs.get("use_lineup") is True

    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api._simulation_helpers.get_team_info")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_lineup_team_info_missing_returns_false(
        self, mock_service, mock_team_profile, mock_team_info, mock_predict,
    ):
        """If team info lookup fails, lineup mode is disabled."""
        home_pr = _fake_profile_result()
        away_pr = _fake_profile_result()

        async def team_profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            return home_pr if team == "NYY" else away_pr

        mock_team_profile.side_effect = team_profile_side

        # One team not found
        async def team_info_side(team, *, db):
            if team == "NYY":
                return {"id": 1, "name": "New York Yankees"}
            return None

        mock_team_info.side_effect = team_info_side
        mock_predict.return_value = None

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.50,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
            "home_lineup": self._lineup(),
            "away_lineup": self._lineup(),
        })
        assert resp.status_code == 200
        # Lineup mode should NOT be enabled (team info missing)
        call_kwargs = mock_service.run_full_simulation.call_args
        assert call_kwargs.kwargs.get("use_lineup") is False

    @patch("app.analytics.api.analytics_routes._predict_with_game_model")
    @patch("app.analytics.api._simulation_helpers.get_player_rolling_profile")
    @patch("app.analytics.api._simulation_helpers.get_pitcher_rolling_profile")
    @patch("app.analytics.api._simulation_helpers.get_team_info")
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_lineup_exception_falls_back(
        self, mock_service, mock_team_profile, mock_team_info,
        mock_pitcher_profile, mock_player_profile, mock_predict,
    ):
        """If _build_lineup_context raises, falls back to team-level."""
        home_pr = _fake_profile_result()
        away_pr = _fake_profile_result()

        async def team_profile_side(team, sport, *, rolling_window, exclude_playoffs, db):
            return home_pr if team == "NYY" else away_pr

        mock_team_profile.side_effect = team_profile_side

        async def team_info_side(team, *, db):
            return {"id": 1, "name": "Team"}

        mock_team_info.side_effect = team_info_side
        mock_pitcher_profile.return_value = None

        # Force exception during batter profile fetch
        async def player_side(ref, team_id, *, rolling_window, exclude_playoffs, db):
            raise RuntimeError("DB connection lost")

        mock_player_profile.side_effect = player_side
        mock_predict.return_value = None

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.50,
        }

        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
            "home_lineup": self._lineup(),
            "away_lineup": self._lineup(),
        })
        assert resp.status_code == 200
        # Should fall back, use_lineup=False because exception occurred
        call_kwargs = mock_service.run_full_simulation.call_args
        assert call_kwargs.kwargs.get("use_lineup") is False

    def test_lineup_wrong_count_ignored(self):
        """If lineups don't have exactly 9 batters, lineup mode is skipped."""
        with patch("app.analytics.api.analytics_routes._service") as mock_service, \
             patch("app.analytics.api.analytics_routes.get_team_rolling_profile") as mock_tp:
            mock_tp.return_value = None
            mock_service.run_full_simulation.return_value = {
                "home_win_probability": 0.50,
            }
            client, _ = _make_client()
            resp = client.post("/api/analytics/simulate", json={
                "sport": "mlb",
                "iterations": 500,
                "home_lineup": [{"external_ref": "p1", "name": "P1"}] * 8,  # only 8
                "away_lineup": [{"external_ref": "p1", "name": "P1"}] * 9,
            })
            assert resp.status_code == 200
            call_kwargs = mock_service.run_full_simulation.call_args
            assert call_kwargs.kwargs.get("use_lineup") is False


# ---------------------------------------------------------------------------
# GET /mlb-roster (lines 767-770)
# ---------------------------------------------------------------------------


class TestGetMLBRoster:
    @patch("app.analytics.api.analytics_routes.get_team_roster")
    def test_roster_found(self, mock_roster):
        async def side(team, *, db):
            return {
                "batters": [{"name": "Judge", "external_ref": "abc"}],
                "pitchers": [{"name": "Cole", "external_ref": "def"}],
            }

        mock_roster.side_effect = side
        client, _ = _make_client()
        resp = client.get("/api/analytics/mlb-roster?team=NYY")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["batters"]) == 1
        assert len(data["pitchers"]) == 1

    @patch("app.analytics.api.analytics_routes.get_team_roster")
    def test_roster_not_found(self, mock_roster):
        mock_roster.return_value = None
        client, _ = _make_client()
        resp = client.get("/api/analytics/mlb-roster?team=XYZ")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["batters"] == []
        assert data["pitchers"] == []


# ---------------------------------------------------------------------------
# _predict_with_game_model (lines 653-708)
# ---------------------------------------------------------------------------


class TestPredictWithGameModel:
    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile")
    @patch("app.analytics.api.analytics_routes._service")
    def test_predict_game_model_no_job(self, mock_service, mock_tp):
        """When no completed training job exists, returns None."""
        mock_tp.return_value = None

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.50,
        }

        # The mock_db default has scalar_one_or_none returning None
        client, _ = _make_client()
        resp = client.post("/api/analytics/simulate", json={
            "sport": "mlb",
            "home_team": "NYY",
            "away_team": "BOS",
            "iterations": 500,
        })
        assert resp.status_code == 200
        data = resp.json()
        # No model prediction when no job found
        assert "model_home_win_probability" not in data
