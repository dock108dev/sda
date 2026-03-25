"""Route-level tests for the multi-sport simulator endpoints.

Covers:
- GET /api/simulator/{sport}/teams for nba, nhl, ncaab, and unsupported sports
- POST /api/simulator/{sport} for nba, nhl, ncaab
- Backward compatibility for existing MLB-specific endpoints
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.services.profile_service import ProfileResult
from app.db import get_db
from app.routers.simulator import router


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


# ---------------------------------------------------------------------------
# GET /api/simulator/{sport}/teams
# ---------------------------------------------------------------------------


class TestListSportTeamsNBA:
    """GET /api/simulator/nba/teams"""

    def test_returns_empty_teams(self) -> None:
        client = _make_client()
        resp = client.get("/api/simulator/nba/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nba"
        assert data["teams"] == []
        assert data["count"] == 0

    def test_returns_teams_with_stats(self) -> None:
        mock_db = AsyncMock()
        mock_row = MagicMock()
        mock_row.abbreviation = "BOS"
        mock_row.name = "Boston Celtics"
        mock_row.short_name = "Celtics"
        mock_row.games_with_stats = 55
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/simulator/nba/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nba"
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "BOS"
        assert data["teams"][0]["games_with_stats"] == 55


class TestListSportTeamsNHL:
    """GET /api/simulator/nhl/teams"""

    def test_returns_empty_teams(self) -> None:
        client = _make_client()
        resp = client.get("/api/simulator/nhl/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nhl"
        assert data["teams"] == []
        assert data["count"] == 0

    def test_returns_teams_with_stats(self) -> None:
        mock_db = AsyncMock()
        mock_row = MagicMock()
        mock_row.abbreviation = "BOS"
        mock_row.name = "Boston Bruins"
        mock_row.short_name = "Bruins"
        mock_row.games_with_stats = 40
        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row]
        mock_db.execute.return_value = mock_result

        client = _make_client(mock_db)
        resp = client.get("/api/simulator/nhl/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nhl"
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "BOS"


class TestListSportTeamsNCAAB:
    """GET /api/simulator/ncaab/teams"""

    def test_returns_empty_teams(self) -> None:
        client = _make_client()
        resp = client.get("/api/simulator/ncaab/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "ncaab"
        assert data["teams"] == []
        assert data["count"] == 0


class TestListSportTeamsUnsupported:
    """GET /api/simulator/{unsupported}/teams returns 400."""

    def test_unknown_sport_returns_400(self) -> None:
        client = _make_client()
        resp = client.get("/api/simulator/cricket/teams")
        assert resp.status_code == 400
        data = resp.json()
        assert "Unsupported sport" in data["detail"]

    def test_empty_sport_returns_400(self) -> None:
        # "unknown" as a sport
        client = _make_client()
        resp = client.get("/api/simulator/unknown/teams")
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/simulator/{sport}
# ---------------------------------------------------------------------------

_SIMULATION_RESULT = {
    "home_win_probability": 0.56,
    "away_win_probability": 0.44,
    "average_home_score": 105.2,
    "average_away_score": 100.8,
    "average_total": 206.0,
    "most_common_scores": [
        {"score": "105-101", "probability": 0.04},
    ],
}


class TestSimulateGameNBA:
    """POST /api/simulator/nba"""

    @patch("app.routers.simulator._predict_with_game_model", new_callable=AsyncMock)
    @patch("app.routers.simulator.get_team_rolling_profile", new_callable=AsyncMock)
    @patch("app.routers.simulator._service")
    def test_runs_simulation_no_profiles(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        mock_profile.return_value = None
        mock_model_predict.return_value = None
        mock_service.run_full_simulation.return_value = _SIMULATION_RESULT

        client = _make_client()
        resp = client.post("/api/simulator/nba", json={
            "home_team": "BOS",
            "away_team": "MIA",
            "iterations": 100,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nba"
        assert data["home_team"] == "BOS"
        assert data["away_team"] == "MIA"
        assert data["home_win_probability"] == 0.56
        assert data["profiles_loaded"] is False
        assert data["iterations"] == 100

    @patch("app.routers.simulator._predict_with_game_model", new_callable=AsyncMock)
    @patch("app.routers.simulator.get_team_rolling_profile", new_callable=AsyncMock)
    @patch("app.routers.simulator._service")
    def test_runs_simulation_with_profiles(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        metrics = {"efg_pct": 0.54, "tov_pct": 0.12, "orb_pct": 0.28}
        mock_profile.return_value = ProfileResult(
            metrics=metrics,
            games_used=30,
            date_range=("2026-02-10", "2026-03-10"),
        )
        mock_model_predict.return_value = 0.60
        mock_service.run_full_simulation.return_value = _SIMULATION_RESULT

        client = _make_client()
        resp = client.post("/api/simulator/nba", json={
            "home_team": "BOS",
            "away_team": "MIA",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nba"
        assert data["profiles_loaded"] is True
        assert data["model_home_win_probability"] == 0.60

    @patch("app.routers.simulator._predict_with_game_model", new_callable=AsyncMock)
    @patch("app.routers.simulator.get_team_rolling_profile", new_callable=AsyncMock)
    @patch("app.routers.simulator._service")
    def test_uses_rule_based_mode(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        """NBA should use rule_based probability mode, not ml."""
        metrics = {"efg_pct": 0.54, "tov_pct": 0.12}
        mock_profile.return_value = ProfileResult(
            metrics=metrics,
            games_used=30,
            date_range=("2026-02-10", "2026-03-10"),
        )
        mock_model_predict.return_value = None
        mock_service.run_full_simulation.return_value = _SIMULATION_RESULT

        client = _make_client()
        client.post("/api/simulator/nba", json={
            "home_team": "BOS",
            "away_team": "MIA",
        })

        call_kwargs = mock_service.run_full_simulation.call_args
        game_context = call_kwargs.kwargs.get("game_context") or call_kwargs[1].get("game_context")
        assert game_context["probability_mode"] == "rule_based"


class TestSimulateGameNHL:
    """POST /api/simulator/nhl"""

    @patch("app.routers.simulator._predict_with_game_model", new_callable=AsyncMock)
    @patch("app.routers.simulator.get_team_rolling_profile", new_callable=AsyncMock)
    @patch("app.routers.simulator._service")
    def test_runs_simulation(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        mock_profile.return_value = None
        mock_model_predict.return_value = None
        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.52,
            "away_win_probability": 0.48,
            "average_home_score": 3.1,
            "average_away_score": 2.8,
            "average_total": 5.9,
            "most_common_scores": [],
        }

        client = _make_client()
        resp = client.post("/api/simulator/nhl", json={
            "home_team": "BOS",
            "away_team": "TOR",
            "iterations": 200,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "nhl"
        assert data["home_team"] == "BOS"
        assert data["away_team"] == "TOR"
        assert data["home_win_probability"] == 0.52


class TestSimulateGameNCAAB:
    """POST /api/simulator/ncaab"""

    @patch("app.routers.simulator._predict_with_game_model", new_callable=AsyncMock)
    @patch("app.routers.simulator.get_team_rolling_profile", new_callable=AsyncMock)
    @patch("app.routers.simulator._service")
    def test_runs_simulation(
        self, mock_service, mock_profile, mock_model_predict,
    ) -> None:
        mock_profile.return_value = None
        mock_model_predict.return_value = None
        mock_service.run_full_simulation.return_value = {
            "home_win_probability": 0.65,
            "away_win_probability": 0.35,
            "average_home_score": 78.3,
            "average_away_score": 68.1,
            "average_total": 146.4,
            "most_common_scores": [],
        }

        client = _make_client()
        resp = client.post("/api/simulator/ncaab", json={
            "home_team": "DUKE",
            "away_team": "UNC",
            "iterations": 500,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["sport"] == "ncaab"
        assert data["home_team"] == "DUKE"
        assert data["away_team"] == "UNC"
        assert data["home_win_probability"] == 0.65


class TestSimulateGameUnsupported:
    """POST /api/simulator/{unsupported} returns 400."""

    def test_unknown_sport_returns_400(self) -> None:
        client = _make_client()
        resp = client.post("/api/simulator/cricket", json={
            "home_team": "IND",
            "away_team": "AUS",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert "Unsupported sport" in data["detail"]


class TestSimulateGameValidation:
    """Request validation for POST /api/simulator/{sport}."""

    def test_missing_away_team(self) -> None:
        client = _make_client()
        resp = client.post("/api/simulator/nba", json={
            "home_team": "BOS",
        })
        assert resp.status_code == 422

    def test_team_too_short(self) -> None:
        client = _make_client()
        resp = client.post("/api/simulator/nba", json={
            "home_team": "B",
            "away_team": "MIA",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Backward compatibility — existing MLB endpoints still work
# ---------------------------------------------------------------------------


class TestMLBTeamsBackwardCompat:
    """GET /api/simulator/mlb/teams — existing endpoint."""

    def test_returns_teams(self) -> None:
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
        # The original MLB endpoint returns teams/count (no sport field)
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "NYY"


class TestMLBSimulateBackwardCompat:
    """POST /api/simulator/mlb — existing endpoint with lineup support."""

    @patch("app.routers.simulator_mlb._predict_with_game_model", new_callable=AsyncMock)
    @patch("app.routers.simulator_mlb.get_team_rolling_profile", new_callable=AsyncMock)
    @patch("app.routers.simulator_mlb._service")
    def test_runs_simulation(
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
            "most_common_scores": [],
        }

        client = _make_client()
        resp = client.post("/api/simulator/mlb", json={
            "home_team": "NYY",
            "away_team": "LAD",
            "iterations": 100,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["home_team"] == "NYY"
        assert data["away_team"] == "LAD"
        assert data["home_win_probability"] == 0.54
        assert data["iterations"] == 100
