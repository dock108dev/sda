"""Integration tests for GET /api/v1/games/{game_id}/flow — consumer endpoint.

Verifies:
- Consumer response shape omits validationPassed / validationErrors
- RECAP_PENDING, non-final status, and 404 paths work correctly
- Auth: missing/invalid API key returns 401
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db import get_db
from app.db.sports import GameStatus
from app.dependencies.consumer_auth import verify_consumer_api_key
from app.routers.v1 import router as v1_router

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

    async def override_auth():
        return "test-key"

    # Use the v1_router so auth dependency is applied at the router level
    app = FastAPI()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_consumer_api_key] = override_auth
    app.include_router(v1_router)
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


def _mock_game(
    status: str = GameStatus.final.value,
    end_time: datetime | None = None,
) -> MagicMock:
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
    flow.moments_json = []
    flow.blocks_json = [
        {
            "block_index": 0,
            "role": "OPENING",
            "moment_indices": [0],
            "period_start": 1,
            "period_end": 1,
            "score_before": [0, 0],
            "score_after": [2, 0],
            "play_ids": [1],
            "key_play_ids": [1],
            "narrative": "Game started strong.",
            "mini_box": None,
            "embedded_social_post_id": None,
            "start_clock": "12:00",
            "end_clock": "11:30",
        }
    ]
    flow.validated_at = datetime(2026, 1, 1, tzinfo=UTC)
    # v2 schema columns — None keeps MagicMock from auto-generating attrs
    # that fail pydantic validation on the response model.
    flow.version = None
    flow.archetype = None
    flow.winner_team_id = None
    flow.source_counts = None
    flow.validation = None
    return flow


# ---------------------------------------------------------------------------
# Consumer response shape
# ---------------------------------------------------------------------------


class TestConsumerResponseShape:
    """Flow data available → ConsumerGameFlowResponse (no validation fields)."""

    def test_returns_flow_without_validation_fields(self) -> None:
        mock_db = AsyncMock()

        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = _mock_flow()

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game()

        plays_result = MagicMock()
        plays_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [flow_result, game_result, plays_result]

        client, _ = _make_client(mock_db)
        resp = client.get("/api/v1/games/42/flow")

        assert resp.status_code == 200
        data = resp.json()

        assert "gameId" in data
        assert data["gameId"] == 42
        assert "blocks" in data
        assert "plays" in data

        # Consumer shape must NOT expose pipeline internals
        assert "validationPassed" not in data
        assert "validationErrors" not in data
        assert "flow" not in data

    def test_score_is_score_object(self) -> None:
        mock_db = AsyncMock()

        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = _mock_flow()

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game()

        plays_result = MagicMock()
        plays_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [flow_result, game_result, plays_result]

        client, _ = _make_client(mock_db)
        resp = client.get("/api/v1/games/42/flow")
        data = resp.json()

        block = data["blocks"][0]
        assert isinstance(block["scoreBefore"], dict)
        assert block["scoreBefore"] == {"home": 0, "away": 0}
        assert block["scoreAfter"] == {"home": 2, "away": 0}

    def test_includes_team_metadata(self) -> None:
        mock_db = AsyncMock()

        flow_result = MagicMock()
        flow_result.scalar_one_or_none.return_value = _mock_flow()

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game()

        plays_result = MagicMock()
        plays_result.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [flow_result, game_result, plays_result]

        client, _ = _make_client(mock_db)
        resp = client.get("/api/v1/games/42/flow")
        data = resp.json()

        assert data["homeTeam"] == "Home Team"
        assert data["awayTeam"] == "Away Team"
        assert data["homeTeamAbbr"] == "HOM"
        assert data["leagueCode"] == "NBA"


# ---------------------------------------------------------------------------
# Status responses
# ---------------------------------------------------------------------------


class TestRecapPendingStatus:
    """FINAL game with no flow → RECAP_PENDING."""

    def test_final_no_flow_returns_recap_pending(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game(
            end_time=datetime.now(UTC) - timedelta(minutes=5)
        )

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/api/v1/games/42/flow")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "RECAP_PENDING"
        assert data["gameId"] == 42
        assert isinstance(data["etaMinutes"], int)

    def test_eta_zero_when_overdue(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game(
            end_time=datetime.now(UTC) - timedelta(minutes=30)
        )

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/api/v1/games/42/flow")
        assert resp.json()["etaMinutes"] == 0


class TestNonFinalStatus:
    """Non-FINAL game states map correctly."""

    @pytest.mark.parametrize(
        "game_status,expected",
        [
            (GameStatus.live.value, "IN_PROGRESS"),
            (GameStatus.pregame.value, "PREGAME"),
            (GameStatus.scheduled.value, "PREGAME"),
            (GameStatus.postponed.value, "POSTPONED"),
            (GameStatus.CANCELLED.value, "CANCELED"),
        ],
    )
    def test_status_mapping(self, game_status: str, expected: str) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None

        game_result = MagicMock()
        game_result.scalar_one_or_none.return_value = _mock_game(status=game_status)

        mock_db.execute.side_effect = [no_flow, game_result]
        client, _ = _make_client(mock_db)

        resp = client.get("/api/v1/games/42/flow")
        assert resp.status_code == 200
        assert resp.json()["status"] == expected


class TestNotFound:
    """Unknown game → 404."""

    def test_missing_game_is_404(self) -> None:
        mock_db = AsyncMock()

        no_flow = MagicMock()
        no_flow.scalar_one_or_none.return_value = None
        no_game = MagicMock()
        no_game.scalar_one_or_none.return_value = None

        mock_db.execute.side_effect = [no_flow, no_game]
        client, _ = _make_client(mock_db)

        resp = client.get("/api/v1/games/99/flow")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Auth enforcement
# ---------------------------------------------------------------------------


class TestConsumerAuth:
    """verify_consumer_api_key raises 401 on bad key."""

    def _make_auth_client(self, monkeypatch) -> TestClient:
        import app.dependencies.consumer_auth as auth_mod

        fake_settings = MagicMock()
        fake_settings.api_key = "real-key-abcdef1234567890abcdef"
        fake_settings.consumer_api_key = None  # Single-key setup; no separate consumer key
        fake_settings.environment = "development"
        monkeypatch.setattr(auth_mod, "settings", fake_settings)

        mock_db = AsyncMock()

        async def override_db():
            yield mock_db

        fastapi_app = FastAPI()
        fastapi_app.dependency_overrides[get_db] = override_db
        # Include v1_router WITHOUT overriding verify_consumer_api_key
        fastapi_app.include_router(v1_router)
        return TestClient(fastapi_app, raise_server_exceptions=False)

    def test_missing_key_raises_401(self, monkeypatch) -> None:
        client = self._make_auth_client(monkeypatch)
        resp = client.get("/api/v1/games/42/flow")
        assert resp.status_code == 401

    def test_wrong_key_raises_401(self, monkeypatch) -> None:
        client = self._make_auth_client(monkeypatch)
        resp = client.get("/api/v1/games/42/flow", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401
