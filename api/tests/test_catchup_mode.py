from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from app.routers.admin.task_control import TASK_REGISTRY
from app.routers.sports.catchup import _enrich_detail_plays, _summary
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

    assert set(detail_data) == {
        "detailContractVersion",
        "game",
        "plays",
        "playerStats",
        "teamStats",
    }
    assert detail_data["detailContractVersion"] == 2
    assert detail_data["game"]["score"] == {"home": 90, "away": 88}


def test_consumer_games_defaults_to_current_slate_sort(monkeypatch) -> None:
    from app.routers.v1 import games as v1_games

    sort_default = inspect.signature(v1_games.list_games).parameters["sort"].default
    assert sort_default.default == "currentSlate"

    calls = {}

    async def fake_list_catchup_games(**kwargs):
        calls.update(kwargs)
        return CatchupGameListResponse(games=[], total=0)

    monkeypatch.setattr(v1_games, "list_catchup_games", fake_list_catchup_games)

    asyncio.run(
        v1_games.list_games(
            session=object(),
            league=None,
            team=None,
            startDate=None,
            endDate=None,
            limit=100,
            offset=0,
            sort="currentSlate",
        )
    )

    assert calls["sort"] == "currentSlate"


def test_catchup_detail_enriches_ios_v2_play_contract() -> None:
    plays = [
        PlayEntry(
            playIndex=1,
            quarter=1,
            gameClock="09:00",
            periodLabel="1st",
            playType="single",
            teamAbbreviation="BOS",
            description="BOS singles to center.",
            score={"home": 0, "away": 0},
        )
    ]

    _enrich_detail_plays(
        game_id=42,
        plays=plays,
        league_code="MLB",
        home_abbr="NYY",
        away_abbr="BOS",
    )
    payload = plays[0].model_dump(by_alias=True, mode="json", exclude_none=True)

    assert payload["displayType"] == "Single"
    assert payload["modeEligibility"]["all"] is True
    assert payload["importance"]["level"] in {"primary", "secondary", "tertiary"}
    assert payload["periodLabel"] == "1st"


def test_catchup_context_builds_spoiler_safe_reasons_from_local_data() -> None:
    team = SimpleNamespace(abbreviation="BOS", short_name="Boston")

    class PlayerWithoutLoadedGame:
        def __init__(self) -> None:
            self.player_name = "Jalen Brunson"
            self.team = team
            self.stats = {"points": 30, "assists": 8}

        @property
        def game(self):  # pragma: no cover - only reached on regression
            raise RuntimeError("context must not lazy-load player.game")

    game = SimpleNamespace(
        id=42,
        league=SimpleNamespace(code="NBA"),
        away_team=SimpleNamespace(name="Boston Celtics", abbreviation="BOS"),
        home_team=SimpleNamespace(name="New York Knicks", abbreviation="NYK"),
        status="final",
        game_date=datetime.now(UTC),
        player_boxscores=[PlayerWithoutLoadedGame()],
        team_boxscores=[SimpleNamespace(team=team, stats={"rebounds": 44, "turnovers": 11})],
        plays=[],
    )

    context = build_catchup_context(game)  # type: ignore[arg-type]

    assert len(context) == 3
    assert "Boston Celtics at New York Knicks" in context[0]
    assert "Jalen Brunson" in context[1]
    assert not any("90" in sentence or "88" in sentence for sentence in context)


def test_catchup_list_summary_does_not_lazy_load_plays() -> None:
    class GameWithoutLoadedPlays:
        id = 42
        league = SimpleNamespace(code="MLB")
        away_team = SimpleNamespace(name="Boston Red Sox", abbreviation="BOS")
        home_team = SimpleNamespace(name="New York Yankees", abbreviation="NYY")
        status = "final"
        game_date = datetime.now(UTC)
        local_game_date = game_date.date()
        home_score = 3
        away_score = 2
        player_boxscores = []
        team_boxscores = []

        @property
        def plays(self):  # pragma: no cover - only reached on regression
            raise RuntimeError("list summaries must not lazy-load game.plays")

    summary = _summary(
        GameWithoutLoadedPlays(),  # type: ignore[arg-type]
        has_boxscore=False,
        has_player_stats=False,
        play_count=17,
        latest_period=7,
        latest_clock="2:30",
    )

    assert summary.id == 42
    assert summary.has_pbp is True
    assert summary.play_count == 17
    assert summary.current_period == 7
    assert summary.game_clock == "2:30"


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
route_owners = {}
route_entries = []
for route in app.routes:
    if route.path in {
        "/api/admin/sports/games",
        "/api/admin/sports/games/{game_id}",
        "/api/admin/sports/games/{game_id}/context",
        "/api/admin/sports/games/{game_id}/admin-detail",
    }:
        route_owners.setdefault(route.path, f"{route.endpoint.__module__}.{route.endpoint.__name__}")
        route_entries.append({
            "path": route.path,
            "methods": sorted(route.methods or []),
            "owner": f"{route.endpoint.__module__}.{route.endpoint.__name__}",
        })
payload = {
    "routes": sorted(route.path for route in app.routes),
    "routeEntries": route_entries,
    "routeOwners": route_owners,
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
    assert "/api/admin/sports/games/{game_id}/admin-detail" in routes
    assert "/api/v1/games" in routes
    assert "/api/v1/games/{game_id}" in routes
    assert (
        sum(
            1
            for entry in payload["routeEntries"]
            if entry["path"] == "/api/admin/sports/games/{game_id}" and "GET" in entry["methods"]
        )
        == 1
    )
    assert payload["routeOwners"] == {
        "/api/admin/sports/games": "app.routers.sports.catchup.list_catchup_games",
        "/api/admin/sports/games/{game_id}": "app.routers.sports.catchup.get_catchup_game",
        "/api/admin/sports/games/{game_id}/context": (
            "app.routers.sports.catchup.get_catchup_game_context"
        ),
        "/api/admin/sports/games/{game_id}/admin-detail": "app.routers.sports.game_detail.get_game",
    }
    assert "/api/admin/sports/scraper/runs" in routes
    assert "/api/admin/sports/logs" in routes
    assert "/api/admin/sports/jobs" in routes
    assert "/api/admin/sports/pipeline/game/{game_id}" in routes
    assert "/api/admin/circuit-breakers" in routes
    assert "/api/admin/coverage-report" in routes
    assert "/api/admin/tasks/registry" in routes
    assert "/api/v1/games" in routes
    assert "/api/v1/games/{game_id}" in routes
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

    assert task_names == {"poll_live_pbp"}
    assert not any(name.startswith("golf_") for name in task_names)
    assert not any("odds" in name for name in task_names)
    assert not any("analytics" in name for name in task_names)
    assert "batch_simulate_games" not in task_names


def test_legacy_admin_games_list_handler_is_absent() -> None:
    games_module = importlib.import_module("app.routers.sports.games")

    assert not hasattr(games_module, "list_games"), (
        "Do not reintroduce app.routers.sports.games.list_games; "
        "the SSOT for GET /api/admin/sports/games is catchup.list_catchup_games."
    )
