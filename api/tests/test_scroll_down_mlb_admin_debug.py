"""Admin debug surface tests for Scroll Down MLB game-detail inspection."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers.sports.game_detail import (
    _half_inning_debug,
    get_game_scroll_down_mlb_debug,
)
from app.scroll_down_mlb.schemas import (
    GenerationOutcome,
    GenerationPolicy,
    HalfInningEvent,
    HalfInningMetaPayload,
    ScrollDownHalfInningContainer,
    ScrollDownMlbDeckResponse,
    TeamSummary,
    ValidationSeverity,
    ValidationWarning,
)


def _run(coro):
    return asyncio.run(coro)


def _team(abbr: str) -> TeamSummary:
    return TeamSummary(id=abbr, abbreviation=abbr, display_name=abbr)


def _deck(
    *,
    last_play_index: int | None = 12,
    half_innings: list[ScrollDownHalfInningContainer] | None = None,
) -> ScrollDownMlbDeckResponse:
    return ScrollDownMlbDeckResponse(
        game_id="123",
        deck_version="live-test",
        generated_at=datetime(2026, 5, 14, tzinfo=UTC),
        is_final=False,
        home_team=_team("HME"),
        away_team=_team("AWY"),
        last_play_index=last_play_index,
        half_innings=half_innings or [],
        validation_warnings=[],
    )


def _game(league_code: str = "MLB", status: str = "live"):
    return SimpleNamespace(
        id=123,
        status=status,
        league=SimpleNamespace(code=league_code),
    )


def _session_for_game(game):
    result = SimpleNamespace(scalar_one_or_none=lambda: game)
    return SimpleNamespace(execute=AsyncMock(return_value=result))


def test_half_inning_debug_reports_container_inconsistencies() -> None:
    container = ScrollDownHalfInningContainer(
        game_id="123",
        inning=1,
        half="top",
        batting_team=_team("AWY"),
        fielding_team=_team("HME"),
        events=[
            HalfInningEvent(sequence=1, play_index=10, is_selected=True),
            HalfInningEvent(sequence=2, play_index=10, is_selected=False),
            HalfInningEvent(sequence=3, play_index=12, is_selected=False),
        ],
        meta=HalfInningMetaPayload(scored_runs=1, had_activity=True),
        selected_play_indices=[10, 99],
    )

    rows, findings = _half_inning_debug(_deck(half_innings=[container]))

    assert rows[0].status == "error"
    codes = {finding.code for finding in findings}
    assert "duplicate_event_play_index" in codes
    assert "selected_play_index_missing_event" in codes
    assert "event_result_label_empty" in codes


def test_scroll_down_debug_returns_not_available_for_non_mlb_game() -> None:
    session = _session_for_game(_game(league_code="NBA"))

    with patch("app.routers.sports.game_detail.scroll_down_mlb_service.get_game_deck") as mock_get:
        response = _run(get_game_scroll_down_mlb_debug(123, session=session))

    assert response.available is False
    assert response.status == "not_available"
    assert "only available for MLB" in (response.reason or "")
    mock_get.assert_not_called()


def test_scroll_down_debug_returns_current_deck_and_validation_summary() -> None:
    container = ScrollDownHalfInningContainer(
        game_id="123",
        inning=1,
        half="bottom",
        batting_team=_team("HME"),
        fielding_team=_team("AWY"),
        events=[HalfInningEvent(sequence=1, play_index=7, is_selected=True)],
        meta=HalfInningMetaPayload(scored_runs=0),
        selected_play_indices=[7],
    )
    deck = _deck(last_play_index=7, half_innings=[container])
    session = _session_for_game(_game())

    with patch(
        "app.routers.sports.game_detail.scroll_down_mlb_service.get_game_deck",
        new=AsyncMock(return_value=deck),
    ):
        response = _run(get_game_scroll_down_mlb_debug(123, session=session))

    assert response.available is True
    assert response.deck_version == "live-test"
    assert response.half_inning_count == 1
    assert response.event_count == 1
    assert response.selected_event_count == 1
    assert response.deck is not None
    assert response.deck["halfInnings"][0]["events"][0]["playIndex"] == 7


def test_scroll_down_debug_surfaces_blocking_generation_errors() -> None:
    session = _session_for_game(_game(status="final"))
    error = ValidationWarning(
        code="home_run_without_score_delta",
        severity=ValidationSeverity.error,
        message="Home run did not change the score.",
        play_id="42",
    )
    outcome = GenerationOutcome(
        policy=GenerationPolicy.official,
        deck=None,
        warnings=[],
        errors=[error],
        blocked=True,
    )

    with (
        patch(
            "app.routers.sports.game_detail.scroll_down_mlb_service.get_game_deck",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.routers.sports.game_detail.load_scroll_down_mlb_payload",
            new=AsyncMock(return_value={"game": {"id": 123}, "plays": []}),
        ),
        patch(
            "app.routers.sports.game_detail.scroll_down_mlb_service.build_deck_from_upstream",
            return_value=outcome,
        ),
    ):
        response = _run(get_game_scroll_down_mlb_debug(123, session=session))

    assert response.available is False
    assert response.status == "blocked"
    assert response.policy == "official"
    assert response.errors[0].code == "home_run_without_score_delta"
