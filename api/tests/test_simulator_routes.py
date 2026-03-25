"""Route-level tests for the simulator endpoints.

Covers: GET /api/simulator/mlb/teams, POST /api/simulator/mlb.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.services.profile_service import ProfileResult
from app.db import get_db
from app.routers.simulator import router

# The MLB endpoints now live in simulator_mlb but are included into the main
# router via include_router.  Patches must target the module where the name
# is looked up at runtime.
_MLB_MOD = "app.routers.simulator_mlb"


def _make_client(mock_db=None):
    """Create a TestClient with mocked DB dependency."""
    if mock_db is None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar_one_or_none.return_value = None
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result

    async def mock_get_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = mock_get_db
    app.include_router(router)
    return TestClient(app)


class TestListSimulatorTeams:
    """GET /api/simulator/mlb/teams"""

    def test_returns_empty_teams(self) -> None:
        client = _make_client()
        resp = client.get("/api/simulator/mlb/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["teams"] == []
        assert data["count"] == 0

    def test_returns_teams_with_stats(self) -> None:
        mock_db = AsyncMock()
        mock_row = MagicMock()
        mock_row.abbreviation = "NYY"
        mock_row.name = "New York Yankees"
        mock_row.short_name = "Yankees"
        mock_row.games_with_stats = 42
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/simulator/mlb/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "NYY"
        assert data["teams"][0]["games_with_stats"] == 42


class TestSimulateMLBGame:
    """POST /api/simulator/mlb"""

    @patch(f"{_MLB_MOD}._predict_with_game_model", new_callable=AsyncMock)
    @patch(f"{_MLB_MOD}.get_team_rolling_profile", new_callable=AsyncMock)
    @patch(f"{_MLB_MOD}._service")
    def test_runs_simulation_no_profiles(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        mock_profile.return_value = None
        mock_model_predict.return_value = None
        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.54,
            "away_win_probability": 0.46,
            "average_home_score": 4.5,
            "average_away_score": 3.8,
            "average_total": 8.3,
            "median_total": 8.0,
            "most_common_scores": [
                {"score": "4-3", "probability": 0.08},
            ],
        }

        client = _make_client()
        resp = client.post("/api/simulator/mlb", json={
            "home_team": "NYY",
            "away_team": "LAD",
            "iterations": 100,
            "seed": 42,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["home_team"] == "NYY"
        assert data["away_team"] == "LAD"
        assert data["home_win_probability"] == 0.54
        assert data["profiles_loaded"] is False
        assert data["iterations"] == 100

    @patch(f"{_MLB_MOD}._predict_with_game_model", new_callable=AsyncMock)
    @patch(f"{_MLB_MOD}.get_team_rolling_profile", new_callable=AsyncMock)
    @patch(f"{_MLB_MOD}._service")
    def test_runs_simulation_with_profiles(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        metrics = {
            "contact_rate": 0.8, "power_index": 0.5, "barrel_rate": 0.08,
            "hard_hit_rate": 0.35, "swing_rate": 0.45, "whiff_rate": 0.25,
            "avg_exit_velocity": 88.0, "expected_slug": 0.4,
        }
        mock_profile.return_value = ProfileResult(
            metrics=metrics,
            games_used=30,
            date_range=("2026-02-10", "2026-03-10"),
        )
        mock_model_predict.return_value = 0.58

        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.58,
            "away_win_probability": 0.42,
            "average_home_score": 5.0,
            "average_away_score": 3.5,
            "average_total": 8.5,
            "median_total": 8.0,
            "most_common_scores": [],
        }

        client = _make_client()
        resp = client.post("/api/simulator/mlb", json={
            "home_team": "NYY",
            "away_team": "BOS",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["profiles_loaded"] is True
        assert data["model_home_win_probability"] == 0.58

    def test_validation_team_too_short(self) -> None:
        client = _make_client()
        resp = client.post("/api/simulator/mlb", json={
            "home_team": "N",
            "away_team": "LAD",
        })
        assert resp.status_code == 422

    def test_validation_missing_away_team(self) -> None:
        client = _make_client()
        resp = client.post("/api/simulator/mlb", json={
            "home_team": "NYY",
        })
        assert resp.status_code == 422
