from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.routers.sports.schemas.catchup import (
    CatchupGameDetailResponse,
    CatchupGameListResponse,
)
from app.routers.sports.schemas.common import PlayEntry, PlayerStat, TeamStat


def test_catchup_schemas_keep_list_spoiler_free_and_detail_complete() -> None:
    game = {
        "id": 1,
        "leagueCode": "NBA",
        "gameDate": datetime.now(UTC),
        "homeTeam": "Home",
        "awayTeam": "Away",
    }
    list_payload = CatchupGameListResponse(games=[game], total=1)
    list_data = list_payload.model_dump(by_alias=True, mode="json", exclude_none=True)

    assert "score" not in list_data["games"][0]
    assert list_data["games"][0]["hasPbp"] is False

    detail_payload = CatchupGameDetailResponse(
        game={**game, "season": 2026, "score": {"home": 90, "away": 88}},
        plays=[PlayEntry(playIndex=1, description="Tip")],
        playerStats=[PlayerStat(team="Home", playerName="A", rawStats={"points": 1})],
        teamStats=[TeamStat(team="Home", isHome=True, stats={"points": 90})],
    )
    detail_data = detail_payload.model_dump(by_alias=True, mode="json", exclude_none=True)

    assert set(detail_data) == {"game", "plays", "playerStats", "teamStats"}
    assert detail_data["game"]["score"] == {"home": 90, "away": 88}


def test_catchup_mode_exposes_only_catchup_routes() -> None:
    api_dir = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(api_dir),
        "SDA_CATCHUP_ONLY": "true",
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
        "API_KEY": "test",
        "AUTH_ENABLED": "false",
        "ENVIRONMENT": "development",
        "MODEL_SIGNING_KEY": "test-signing-key-for-unit-tests-min32chars",
    }
    script = """
import json
from main import app
print("ROUTES=" + json.dumps(sorted(route.path for route in app.routes)))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=api_dir,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    routes_line = next(line for line in result.stdout.splitlines() if line.startswith("ROUTES="))
    routes = set(json.loads(routes_line.removeprefix("ROUTES=")))

    assert "/api/admin/sports/games" in routes
    assert "/api/admin/sports/games/{game_id}" in routes
    assert not any("/api/admin/golf" in route for route in routes)
    assert "/api/admin/sports/jobs" not in routes
    assert "/v1/realtime/status" not in routes
