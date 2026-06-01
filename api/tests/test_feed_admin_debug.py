from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.db.sports import GameStatus, SportsGamePlay, SportsTeam
from app.feed.schemas import SpoilerPolicy
from app.feed.service import build_card_generation_debug_from_game
from app.routers.sports.game_detail import (
    get_game_card_generation_debug as get_admin_card_generation_debug,
)


def _team(
    *,
    team_id: int,
    name: str,
    abbreviation: str,
) -> SportsTeam:
    return SportsTeam(
        id=team_id,
        league_id=1,
        name=name,
        short_name=name,
        abbreviation=abbreviation,
    )


def _game(
    *,
    league: str = "NBA",
    status: str = GameStatus.final.value,
    description: str = "Alex Morgan makes a layup.",
    home_score: int = 2,
    away_score: int = 0,
    home_abbreviation: str = "HOM",
    plays: list[SportsGamePlay] | None = None,
) -> SimpleNamespace:
    home = _team(team_id=1, name=f"{league} Home", abbreviation=home_abbreviation)
    away = _team(team_id=2, name=f"{league} Away", abbreviation="AWY")
    game_plays = plays
    if game_plays is None:
        game_plays = [
            SportsGamePlay(
                game_id=42,
                quarter=4,
                game_clock="01:23",
                play_index=7,
                play_type="layup",
                team=home,
                player_name="Alex Morgan",
                description=description,
                home_score=home_score,
                away_score=away_score,
                raw_data={},
            )
        ]
    return SimpleNamespace(
        id=42,
        league=SimpleNamespace(code=league),
        home_team=home,
        away_team=away,
        plays=game_plays,
        status=status,
        last_pbp_at=None,
        last_ingested_at=None,
    )


def _run(coro):
    return asyncio.run(coro)


def _session_for_game(game: SimpleNamespace) -> SimpleNamespace:
    result = SimpleNamespace(scalar_one_or_none=lambda: game)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


def test_admin_card_generation_debug_endpoint_returns_debug_response() -> None:
    response = _run(
        get_admin_card_generation_debug(
            42,
            spoiler_policy="pre_reveal",
            through_play_index=None,
            include_feed=True,
            session=_session_for_game(_game()),
        )
    )

    assert response.available is True
    assert response.feed is not None
    assert response.feed["cards"][0]["playIndex"] == 7


def test_card_generation_debug_reports_available_feed_with_public_aliases() -> None:
    response = build_card_generation_debug_from_game(_game(), SpoilerPolicy.pre_reveal)

    assert response.available is True
    assert response.status == "available"
    assert response.policy == "official"
    assert response.card_count == 1
    assert response.last_play_index == 7
    assert response.generation_version
    assert response.source_hash
    assert response.cache_state == "generated_on_request"
    assert response.feed is not None
    assert response.feed["cards"][0]["playIndex"] == 7


def test_card_generation_debug_reports_not_available_when_source_has_no_plays() -> None:
    response = build_card_generation_debug_from_game(
        _game(league="NHL", status=GameStatus.live.value, plays=[]),
        SpoilerPolicy.pre_reveal,
    )

    assert response.available is False
    assert response.status == "not_available"
    assert response.policy == "live"
    assert response.card_count == 0
    assert response.cache_state == "empty"
    assert response.reason == "No play-by-play source data is available for this game."


def test_card_generation_debug_reports_blocked_adapter_consistency_error() -> None:
    response = build_card_generation_debug_from_game(
        _game(home_abbreviation=""),
        SpoilerPolicy.pre_reveal,
    )

    assert response.available is False
    assert response.status == "blocked"
    assert response.policy == "official"
    assert response.errors[0].code == "detail_contract_invalid"
    assert response.errors[0].severity == "error"
    assert response.errors[0].scope == "sport_adapter"


def test_card_generation_debug_reports_validation_warning() -> None:
    response = build_card_generation_debug_from_game(
        _game(description="This play would go on to matter later."),
        SpoilerPolicy.pre_reveal,
    )

    assert response.available is True
    assert response.status == "available"
    assert response.warnings[0].code == "narrative_future_spoiler_phrase"
    assert response.warnings[0].play_id == "7"
    assert response.errors == []


def test_card_generation_debug_reports_validation_error_with_fallback_card() -> None:
    response = build_card_generation_debug_from_game(
        _game(
            description="Alex Morgan would go on to seal the 4-2 final score.",
            home_score=4,
            away_score=2,
        ),
        SpoilerPolicy.pre_reveal,
    )

    assert response.available is True
    assert response.status == "available"
    assert {finding.code for finding in response.errors} >= {
        "narrative_final_score_leak",
        "narrative_future_spoiler_phrase",
    }
    assert response.feed is not None
    assert (
        response.feed["cards"][0]["description"]
        == "Verified play detail is available after reveal."
    )
