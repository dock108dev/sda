"""Integration tests for GET /games/{game_id}/flow endpoint.

Covers ISSUE-009: recap-pending state instead of 404 for final games with no flow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.sports import GameStatus
from app.routers.sports.game_timeline import router


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(mock_db: AsyncMock | None = None) -> tuple[TestClient, AsyncMock]:
    if mock_db is None:
        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        result_mock.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = result_mock

    async def override_db():
        yield mock_db

    app = FastAPI()
    app.dependency_overrides[get_db] = override_db
    app.include_router(router)
    return TestClient(app), mock_db


def _mock_team(team_name: str, abbr: str) -> MagicMock:
    t = MagicMock()
    t.name = team_name
    t.abbreviation = abbr
    t.color_light_hex = None
    t.color_dark_hex = None
    t.color_secondary_light_hex = None
    t.color_secondary_dark_hex = None
    return t


def _mock_game(status: str = GameStatus.final.value, end_time: datetime | None = None) -> MagicMock:
    game = MagicMock()
    game.id = 42
    game.status = status
    game.end_time = end_time
    game.home_team = _mock_team("Home Team", "HOM")
    game.away_team = _mock_team("Away Team", "AWY")
    game.league = MagicMock()
    game.league.code = "NBA"
    return game


def _mock_flow(game_id: int = 42) -> MagicMock:
    flow = MagicMock()
    flow.game_id = game_id
    flow.moments_json = [
        {
            "play_ids": [1],
            "explicitly_narrated_play_ids": [1],
            "period": 1,
            "start_clock": "12:00",
            "end_clock": "11:30",
            "score_before": [0, 0],
            "score_after": [2, 0],
            "narrative": "Game started.",
            "cumulative_box_score": None,
        }
    ]
    flow.blocks_json = None
    flow.validated_at = datetime(2026, 1, 1, tzinfo=UTC)
    return flow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFlowEndpointNoPendingState:
    """FINAL game with existing flow → full GameFlowResponse."""

    def test_returns_flow_data(self) -> None:
        mock_db = AsyncMock()

        # First execute: return flow record
        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = _mock_flow()

        # Second execute: return plays (empty)
        plays_result = MagicMock()
        plays_result.scalars.return_value.all.return_value = []

        # Third execute: return game record for colors/metadata
        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game()

        mock_db.execute.side_effect = [flow_result, game_result, plays_result]

        client, _ = _make_client(mock_db)
        resp = client.get("/games/42/flow")
        assert resp.status_code == 200
        data = resp.json()
        assert "flow" in data
        assert "gameId" in data
        assert data["gameId"] == 42
        assert "status" not in data  # GameFlowResponse has no top-level status
        # Verify scores are ScoreObject {home, away}, not [int, int] tuples
        moment = data["flow"]["moments"][0]
        assert isinstance(moment["scoreBefore"], dict)
        assert "home" in moment["scoreBefore"]
        assert "away" in moment["scoreBefore"]
        assert moment["scoreBefore"] == {"home": 0, "away": 0}
        assert moment["scoreAfter"] == {"home": 2, "away": 0}


class TestFlowEndpointRecapPending:
    """FINAL game with no flow → RECAP_PENDING."""

    def test_no_flow_final_game_returns_recap_pending(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game(
            status=GameStatus.final.value,
            end_time=datetime.now(UTC) - timedelta(minutes=5),
        )

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/games/42/flow")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RECAP_PENDING"
        assert data["gameId"] == 42
        assert "etaMinutes" in data
        assert isinstance(data["etaMinutes"], int)
        assert data["etaMinutes"] >= 0

    def test_eta_positive_when_end_time_recent(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        # Game ended 1 minute ago; ETA = 14 minutes remaining
        game_result.scalar_one_or_none.return_value = _mock_game(
            end_time=datetime.now(UTC) - timedelta(minutes=1)
        )

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/games/42/flow")
        assert resp.status_code == 200
        assert resp.json()["etaMinutes"] > 0

    def test_eta_zero_when_overdue(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        # Game ended 30 minutes ago; ETA has passed
        game_result.scalar_one_or_none.return_value = _mock_game(
            end_time=datetime.now(UTC) - timedelta(minutes=30)
        )

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/games/42/flow")
        assert resp.status_code == 200
        assert resp.json()["etaMinutes"] == 0

    def test_eta_uses_15min_fallback_when_no_end_time(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game(end_time=None)

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/games/42/flow")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RECAP_PENDING"
        # With no end_time, ETA is ~15 min from now
        assert 14 <= data["etaMinutes"] <= 15


class TestFlowEndpointNonFinalGame:
    """Non-FINAL games → distinct status (not RECAP_PENDING)."""

    @pytest.mark.parametrize(
        "game_status,expected_flow_status",
        [
            (GameStatus.live.value, "IN_PROGRESS"),
            (GameStatus.pregame.value, "PREGAME"),
            (GameStatus.scheduled.value, "PREGAME"),
            (GameStatus.postponed.value, "POSTPONED"),
            (GameStatus.CANCELLED.value, "CANCELED"),
        ],
    )
    def test_non_final_status_mapping(self, game_status: str, expected_flow_status: str) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game(status=game_status)

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/games/42/flow")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == expected_flow_status
        assert data["gameId"] == 42
        assert "etaMinutes" not in data or data.get("etaMinutes") is None


class TestFlowEndpointGameNotFound:
    """Non-existent game → 404."""

    def test_missing_game_is_404(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        no_game = MagicMock()
        no_game.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [no_flow, no_game]
        client, _ = _make_client(mock_db)

        resp = client.get("/games/99/flow")
        assert resp.status_code == 404
