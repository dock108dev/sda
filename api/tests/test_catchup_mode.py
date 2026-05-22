from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.routers.admin.task_control import TASK_REGISTRY
from app.routers.sports.schemas.catchup import (
    CatchupGameDetailResponse,
    CatchupGameListResponse,
)
from app.routers.sports.schemas.common import PlayEntry, PlayerStat, TeamStat
from app.services.catchup_context import build_catchup_context


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


def test_catchup_context_builds_spoiler_safe_reasons_from_local_data() -> None:
    team = SimpleNamespace(abbreviation="BOS", short_name="Boston")
    game = SimpleNamespace(
        id=42,
        league=SimpleNamespace(code="NBA"),
        away_team=SimpleNamespace(name="Boston Celtics", abbreviation="BOS"),
        home_team=SimpleNamespace(name="New York Knicks", abbreviation="NYK"),
        status="final",
        game_date=datetime.now(UTC),
        player_boxscores=[
            SimpleNamespace(
                player_name="Jalen Brunson",
                team=team,
                stats={"points": 30, "assists": 8},
                game=SimpleNamespace(league=SimpleNamespace(code="NBA")),
            )
        ],
        team_boxscores=[SimpleNamespace(team=team, stats={"rebounds": 44, "turnovers": 11})],
        plays=[],
    )

    context = build_catchup_context(game)  # type: ignore[arg-type]

    assert len(context) == 3
    assert "Boston Celtics at New York Knicks" in context[0]
    assert "Jalen Brunson" in context[1]
    assert not any("90" in sentence or "88" in sentence for sentence in context)


def test_admin_surface_keeps_sports_and_system_routes_only() -> None:
    api_dir = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": str(api_dir),
        "DATABASE_URL": "postgresql+asyncpg://test:test@localhost/test",
        "API_KEY": "test",
        "AUTH_ENABLED": "false",
        "ENVIRONMENT": "development",
        "MODEL_SIGNING_KEY": "test-signing-key-for-unit-tests-min32chars",
    }
    script = """
import json
from app.config import settings
from main import app
payload = {
    "routes": sorted(route.path for route in app.routes),
    "has_catchup_only_setting": hasattr(settings, "catchup_only"),
}
print("APP=" + json.dumps(payload))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=api_dir,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    app_line = next(line for line in result.stdout.splitlines() if line.startswith("APP="))
    payload = json.loads(app_line.removeprefix("APP="))
    routes = set(payload["routes"])

    assert payload["has_catchup_only_setting"] is False
    assert "/api/admin/sports/games" in routes
    assert "/api/admin/sports/games/{game_id}" in routes
    assert "/api/admin/sports/games/{game_id}/context" in routes
    assert "/api/admin/sports/scraper/runs" in routes
    assert "/api/admin/sports/logs" in routes
    assert "/api/admin/sports/jobs" in routes
    assert "/api/admin/sports/pipeline/game/{game_id}" in routes
    assert "/api/admin/circuit-breakers" in routes
    assert "/api/admin/coverage-report" in routes
    assert "/api/admin/tasks/registry" in routes
    assert "/api/v1/games/{game_id}/summary" in routes
    assert not any(route.startswith("/api/admin/golf") for route in routes)
    assert not any(route.startswith("/api/golf") for route in routes)
    assert not any(route.startswith("/api/analytics") for route in routes)
    assert not any(route.startswith("/api/fairbet") for route in routes)
    assert not any(route.startswith("/api/model-odds") for route in routes)
    assert not any(route.startswith("/api/simulator") for route in routes)
    assert "/api/auth/login" not in routes


def test_task_registry_excludes_disabled_odds_analytics_and_golf() -> None:
    task_names = set(TASK_REGISTRY)

    assert {"run_scheduled_ingestion", "poll_live_pbp", "trigger_flow_for_game"} <= task_names
    assert not any(name.startswith("golf_") for name in task_names)
    assert not any("odds" in name for name in task_names)
    assert not any("analytics" in name for name in task_names)
    assert "batch_simulate_games" not in task_names
