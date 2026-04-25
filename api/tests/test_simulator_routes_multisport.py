"""Route-level tests for the multi-sport simulator endpoints.

Covers:
- GET /api/simulator/{sport}/teams for nba, nhl, ncaab, and unsupported sports
- POST /api/simulator/{sport} for nba, nhl, ncaab
- Backward compatibility for existing MLB-specific endpoints
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
        assert data["teams"][0]["gamesWithStats"] == 55


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


class TestCanonicalAbbrFilter:
    """Cross-sport contamination guard: each sport's /teams query must
    include the canonical abbr IN-list (except NCAAB, which has no list)."""

    @staticmethod
    def _executed_sql(mock_db: AsyncMock) -> str:
        # Compile each executed statement with literal_binds=True so IN-list
        # values appear inline (otherwise they show as POSTCOMPILE markers).
        compiled: list[str] = []
        for call in mock_db.execute.call_args_list:
            stmt = call.args[0]
            try:
                compiled.append(
                    str(stmt.compile(compile_kwargs={"literal_binds": True}))
                )
            except Exception:
                compiled.append(str(stmt))
        return "\n".join(compiled)

    def _make_db(self) -> AsyncMock:
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db.execute.return_value = mock_result
        return mock_db

    def test_mlb_filters_by_canonical_abbrs(self) -> None:
        mock_db = self._make_db()
        client = _make_client(mock_db)
        resp = client.get("/api/simulator/mlb/teams")
        assert resp.status_code == 200
        sql = self._executed_sql(mock_db)
        # Each canonical abbr should appear as a bound IN value in the compiled
        # SQL (sqlalchemy ClauseList renders them inline at __str__ time).
        for abbr in ("NYY", "LAD", "BOS"):
            assert abbr in sql, f"MLB query missing canonical abbr {abbr}"

    def test_nba_filters_by_canonical_abbrs(self) -> None:
        mock_db = self._make_db()
        client = _make_client(mock_db)
        resp = client.get("/api/simulator/nba/teams")
        assert resp.status_code == 200
        sql = self._executed_sql(mock_db)
        for abbr in ("BOS", "LAL", "GSW"):
            assert abbr in sql, f"NBA query missing canonical abbr {abbr}"

    def test_nhl_filters_by_canonical_abbrs(self) -> None:
        mock_db = self._make_db()
        client = _make_client(mock_db)
        resp = client.get("/api/simulator/nhl/teams")
        assert resp.status_code == 200
        sql = self._executed_sql(mock_db)
        for abbr in ("BOS", "TOR", "VGK"):
            assert abbr in sql, f"NHL query missing canonical abbr {abbr}"
        # Both ARI (historic Coyotes) and UTA (Hockey Club) should be present.
        assert "ARI" in sql
        assert "UTA" in sql

    def test_ncaab_does_not_apply_canonical_filter(self) -> None:
        # NCAAB has 350+ teams; no canonical list. We rely on league_id alone.
        mock_db = self._make_db()
        client = _make_client(mock_db)
        resp = client.get("/api/simulator/ncaab/teams")
        assert resp.status_code == 200
        sql = self._executed_sql(mock_db)
        # No NBA-specific abbr should leak in (proves we didn't accidentally
        # apply the wrong sport's filter).
        # We can't assert "no IN clause" cleanly, but we can assert that we
        # didn't import another sport's list:
        assert "GSW" not in sql
        assert "NYY" not in sql

    def test_team_info_includes_sport_field(self) -> None:
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
        assert data["teams"][0]["sport"] == "nba"


class TestSimulatorThreadOffload:
    """The simulator must run via asyncio.to_thread so concurrent requests
    don't serialize on a single ASGI worker.

    Strategy: replace _service.run_full_simulation with a function that blocks
    on time.sleep (which only releases the GIL when run in a thread pool).
    Issue N concurrent requests via httpx.AsyncClient and assert wall-clock
    is closer to the per-call sleep than to N × per-call sleep.
    """

    @pytest.mark.asyncio
    async def test_concurrent_requests_run_in_parallel(self) -> None:
        import asyncio
        import time

        import httpx

        from app.routers import simulator as sim_module

        per_call_seconds = 0.25
        concurrency = 4

        def _slow_sim(*args, **kwargs):
            # time.sleep releases the GIL — the whole point of to_thread.
            time.sleep(per_call_seconds)
            return _SIMULATION_RESULT

        client = _make_client()
        with (
            patch.object(sim_module, "_service") as mock_service,
            patch(
                "app.routers.simulator.get_team_rolling_profile",
                new_callable=AsyncMock,
            ) as mock_profile,
            patch(
                "app.routers.simulator._predict_with_game_model",
                new_callable=AsyncMock,
            ) as mock_predict,
        ):
            mock_profile.return_value = None
            mock_predict.return_value = None
            mock_service.run_full_simulation.side_effect = _slow_sim

            transport = httpx.ASGITransport(app=client.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as ac:
                start = time.perf_counter()
                results = await asyncio.gather(*[
                    ac.post(
                        "/api/simulator/nba",
                        json={
                            "home_team": "BOS",
                            "away_team": "MIA",
                            "iterations": 100,
                        },
                    )
                    for _ in range(concurrency)
                ])
                elapsed = time.perf_counter() - start

        assert all(r.status_code == 200 for r in results)
        # Serial wall-clock would be ~ concurrency * per_call_seconds = 1.0s.
        # Parallel via to_thread should finish in well under 2x per_call.
        assert elapsed < per_call_seconds * 2.5, (
            f"simulator did not parallelize: elapsed={elapsed:.2f}s, "
            f"expected < {per_call_seconds * 2.5:.2f}s"
        )


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
        assert data["homeTeam"] == "BOS"
        assert data["awayTeam"] == "MIA"
        assert data["homeWinProbability"] == 0.56
        assert data["profilesLoaded"] is False
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
        assert data["profilesLoaded"] is True
        assert data["modelHomeWinProbability"] == 0.60

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
        assert data["homeTeam"] == "BOS"
        assert data["awayTeam"] == "TOR"
        assert data["homeWinProbability"] == 0.52


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
        assert data["homeTeam"] == "DUKE"
        assert data["awayTeam"] == "UNC"
        assert data["homeWinProbability"] == 0.65


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


class TestMLBTeamsRoute:
    """GET /api/simulator/mlb/teams — served by the generic /{sport}/teams handler."""

    def test_returns_teams_with_sport_field(self) -> None:
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
        assert data["sport"] == "mlb"
        assert data["count"] == 1
        assert data["teams"][0]["abbreviation"] == "NYY"
        assert data["teams"][0]["sport"] == "mlb"


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
        assert data["homeTeam"] == "NYY"
        assert data["awayTeam"] == "LAD"
        assert data["homeWinProbability"] == 0.54
        assert data["iterations"] == 100
