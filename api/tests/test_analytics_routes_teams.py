"""Route-level tests for multi-sport team endpoints.

Covers:
- GET /api/analytics/{sport}/teams  (generic multi-sport teams)
- GET /api/analytics/team-profile?sport=...  (sport-aware profile)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.api.analytics_routes import router
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


def _make_team_row(*, id=1, name="Boston Celtics", short_name="Celtics",
                   abbreviation="BOS", games_with_stats=50):
    row = MagicMock()
    row.id = id
    row.name = name
    row.short_name = short_name
    row.abbreviation = abbreviation
    row.games_with_stats = games_with_stats
    return row


# ---------------------------------------------------------------------------
# GET /{sport}/teams
# ---------------------------------------------------------------------------


class TestGetSportTeams:
    """GET /api/analytics/{sport}/teams"""

    def test_unsupported_sport_returns_error(self) -> None:
        client, _ = _make_client()
        resp = client.get("/api/analytics/cricket/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["teams"] == []
        assert data["count"] == 0

    def test_nba_teams_returns_rows(self) -> None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        row = _make_team_row(id=10, name="Boston Celtics", short_name="Celtics",
                             abbreviation="BOS", games_with_stats=42)
        mock_result.all.return_value = [row]
        mock_db.execute.return_value = mock_result

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/nba/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "BOS"
        assert data["teams"][0]["games_with_stats"] == 42

    def test_mlb_teams_returns_rows(self) -> None:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        row = _make_team_row(id=1, name="New York Yankees", short_name="Yankees",
                             abbreviation="NYY", games_with_stats=30)
        mock_result.all.return_value = [row]
        mock_db.execute.return_value = mock_result

        client, _ = _make_client(mock_db)
        resp = client.get("/api/analytics/mlb/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "NYY"

    def test_empty_sport_returns_empty(self) -> None:
        client, _ = _make_client()
        resp = client.get("/api/analytics/nhl/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["teams"] == []
        assert data["count"] == 0

    def test_case_insensitive_sport(self) -> None:
        """Sport path param is lowercased internally."""
        client, _ = _make_client()
        resp = client.get("/api/analytics/NBA/teams")
        assert resp.status_code == 200
        data = resp.json()
        # Should not return an error — NBA is valid
        assert "error" not in data


# ---------------------------------------------------------------------------
# GET /team-profile?sport=...
# ---------------------------------------------------------------------------


class TestGetTeamProfileMultiSport:
    """GET /api/analytics/team-profile with sport param"""

    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile", new_callable=AsyncMock)
    def test_defaults_to_mlb(self, mock_get_profile) -> None:
        """Without sport param, defaults to mlb."""
        mock_get_profile.return_value = None

        client, _ = _make_client()
        resp = client.get("/api/analytics/team-profile?team=NYY")
        assert resp.status_code == 200

        # Verify get_team_rolling_profile was called with "mlb"
        mock_get_profile.assert_called_once()
        call_args = mock_get_profile.call_args
        assert call_args[0][1] == "mlb"

    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile", new_callable=AsyncMock)
    def test_nba_sport_uses_nba_baselines(self, mock_get_profile) -> None:
        """sport=nba should call profile with 'nba' and use NBA baselines."""
        mock_get_profile.return_value = ProfileResult(
            metrics={"pace": 100.0, "offensive_rating": 112.5},
            games_used=20,
            date_range=("2025-11-01", "2025-12-01"),
            season_breakdown={2025: 20},
        )

        client, _ = _make_client()
        resp = client.get("/api/analytics/team-profile?team=BOS&sport=nba")
        assert resp.status_code == 200
        data = resp.json()

        # Verify profile service was called with nba
        call_args = mock_get_profile.call_args
        assert call_args[0][1] == "nba"

        assert data["team"] == "BOS"
        assert data["games_used"] == 20
        assert "metrics" in data
        assert "baselines" in data

    @patch("app.analytics.api.analytics_routes.get_team_rolling_profile", new_callable=AsyncMock)
    def test_no_profile_returns_empty(self, mock_get_profile) -> None:
        mock_get_profile.return_value = None

        client, _ = _make_client()
        resp = client.get("/api/analytics/team-profile?team=XXX&sport=nhl")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data
        assert data["games_used"] == 0
