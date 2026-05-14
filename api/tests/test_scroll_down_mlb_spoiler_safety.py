"""Spoiler-safety tests.

These are the tests the migration is *for*. They guard against:
  * scores or winners showing up on /recent
  * final-score-shaped fields showing up on /deck
  * scoreAfter ever appearing on the deck wire
  * the reveal endpoint being the ONLY place where final score is OK

Implemented as recursive key/value walks over the JSON response so a future
nested field can't hide.
"""

from __future__ import annotations

import re
from datetime import UTC
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scroll_down_mlb.router import router as scroll_down_mlb_router

# Field names that must never appear in pre-reveal payloads.
FORBIDDEN_PRE_REVEAL_KEYS = frozenset(
    {
        "homeScore",
        "awayScore",
        "score",
        "scoreAfter",
        "finalScore",
        "winner",
        "winnerTeamId",
        "winningTeam",
        "result",
        "outcome",
    }
)

# Field names that signal "final state" — also forbidden on /recent.
FORBIDDEN_RECENT_KEYS = FORBIDDEN_PRE_REVEAL_KEYS | frozenset({"runs", "totalRuns"})


@pytest.fixture
def client():
    """Spoiler-safety test client with stubbed service-layer responses.

    Uses a context-managed MonkeyPatch so the stubs on
    `app.scroll_down_mlb.service` are torn down after each test instead
    of leaking into unrelated tests that may import the same module.
    """
    from datetime import datetime
    from unittest.mock import AsyncMock

    from app.db import get_db
    from app.scroll_down_mlb import service as sdm_service
    from app.scroll_down_mlb.schemas import (
        BaseState,
        DeckCardType,
        PlannerReport,
        PlayPayload,
        ScoreState,
        ScrollDownMlbDeckCard,
        ScrollDownMlbDeckResponse,
    )

    app = FastAPI()
    app.include_router(scroll_down_mlb_router)
    app.dependency_overrides[get_db] = lambda: AsyncMock()

    # Stub the service so the spoiler-safety walks operate on a deck with
    # at least one play card (the `keeps_score_before` test demands that).
    async def _stub_deck(*_a, **_kw):
        return ScrollDownMlbDeckResponse(
            game_id="190203",
            deck_version="stub-v0",
            generated_at=datetime.now(UTC),
            is_final=False,
            cards=[
                ScrollDownMlbDeckCard(
                    id="190203-play-1",
                    type=DeckCardType.play,
                    sort_order=1,
                    inning=1,
                    half="top",
                    description="Strikes out swinging.",
                    play=PlayPayload(
                        play_id="1",
                        score_before=ScoreState(home=0, away=0),
                        runs_scored_on_play=0,
                        base_state_before=BaseState(),
                        base_state_after=BaseState(),
                    ),
                    leverage_tier=0,
                ),
            ],
            planner_report=PlannerReport(),
            validation_warnings=[],
        )

    async def _empty(*_a, **_kw):
        return []

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sdm_service, "get_game_deck", _stub_deck)
        mp.setattr(sdm_service, "get_recent_games", _empty)
        yield TestClient(app)


def _collect_keys(node: Any) -> set[str]:
    """Recursively collect every JSON object key in `node`."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            keys.add(k)
            keys |= _collect_keys(v)
    elif isinstance(node, list):
        for v in node:
            keys |= _collect_keys(v)
    return keys


# ---------------------------------------------------------------------------
# /games/recent
# ---------------------------------------------------------------------------


def test_recent_response_contains_no_forbidden_keys(client: TestClient) -> None:
    body = client.get("/api/v1/scroll-down-mlb/games/recent").json()
    keys = _collect_keys(body)
    leaks = keys & FORBIDDEN_RECENT_KEYS
    assert not leaks, f"/recent leaked spoiler-shaped keys: {sorted(leaks)}"


# ---------------------------------------------------------------------------
# /games/{id}/deck
# ---------------------------------------------------------------------------


def test_deck_response_contains_no_forbidden_keys(client: TestClient) -> None:
    body = client.get("/api/v1/scroll-down-mlb/games/190203/deck").json()
    keys = _collect_keys(body)
    leaks = keys & FORBIDDEN_PRE_REVEAL_KEYS
    assert not leaks, f"/deck leaked spoiler-shaped keys: {sorted(leaks)}"


def test_deck_response_does_not_contain_score_after_anywhere(
    client: TestClient,
) -> None:
    """Belt-and-suspenders: the JSON text itself must not contain the
    string `scoreAfter`. Catches the case where a future PlayPayload field
    is renamed to bypass `FORBIDDEN_PRE_REVEAL_KEYS` but still ships."""
    raw = client.get("/api/v1/scroll-down-mlb/games/190203/deck").text
    assert not re.search(r'"score_?after"', raw, re.IGNORECASE)


def test_deck_response_keeps_score_before_for_running_score(
    client: TestClient,
) -> None:
    """`scoreBefore` is allowed (and necessary) for the running scoreboard.
    This test pins the contract so a well-meaning future cleanup doesn't
    over-strip."""
    body = client.get("/api/v1/scroll-down-mlb/games/190203/deck").json()
    keys = _collect_keys(body)
    play_cards = [c for c in body.get("cards", []) if c.get("type") == "play"]
    if play_cards:
        # If the stub deck has any play cards, scoreBefore should be present
        # on the play payload.
        assert "scoreBefore" in keys


# ---------------------------------------------------------------------------
# /games/{id}/reveal — final score IS allowed here
# ---------------------------------------------------------------------------


def test_reveal_endpoint_is_the_only_place_final_score_is_allowed() -> None:
    """Doc-style invariant: the schema for `ScrollDownMlbRevealResponse`
    declares `final_score` and `winner_team_id`. Other endpoints' schemas
    do not. This pins that division so a future PR adding a "convenience"
    final-score field to the deck schema fails CI."""
    from app.scroll_down_mlb.schemas import (
        ScrollDownMlbDeckResponse,
        ScrollDownMlbRecentGame,
        ScrollDownMlbRevealResponse,
    )

    deck_fields = set(ScrollDownMlbDeckResponse.model_fields.keys())
    recent_fields = set(ScrollDownMlbRecentGame.model_fields.keys())
    reveal_fields = set(ScrollDownMlbRevealResponse.model_fields.keys())

    forbidden = {"final_score", "winner_team_id", "winner"}

    assert (deck_fields & forbidden) == set(), (
        f"Deck schema must not declare final-score fields: {deck_fields & forbidden}"
    )
    assert (recent_fields & forbidden) == set(), (
        f"Recent schema must not declare final-score fields: {recent_fields & forbidden}"
    )
    # And reveal IS allowed to.
    assert "final_score" in reveal_fields
    assert "winner_team_id" in reveal_fields


# ---------------------------------------------------------------------------
# GameSituation post-play snapshot — score must be structurally absent
# ---------------------------------------------------------------------------


def test_post_play_situation_schema_has_no_score_field() -> None:
    """`GameSituationAfter` is the wire type for post-play snapshots. Its
    score-less shape is the structural enforcement that the final play of
    a completed game cannot leak the final score via
    `playPayload.situationAfter.score`."""
    from app.scroll_down_mlb.schemas import GameSituation, GameSituationAfter

    after_fields = set(GameSituationAfter.model_fields.keys())
    before_fields = set(GameSituation.model_fields.keys())

    assert "score" not in after_fields, (
        f"GameSituationAfter must not declare `score` (would leak the final "
        f"score on the last play of a completed game). Got fields: {after_fields}"
    )
    # situation_before keeps `score` — the running pre-play value is safe
    # because every prior card already exposed it.
    assert "score" in before_fields


def test_leak_scanner_catches_nested_situation_after_score() -> None:
    """The path-aware leak scanner walks `situationAfter.score` so a
    future schema change (or a manual response built from a permissive
    dict) cannot leak the final score through the nested path that the
    flat key check is too coarse to disambiguate."""
    from app.scroll_down_mlb.validation import validate_no_final_score_leak

    # Final play of a final game: situationAfter.score == final_score.
    payload = {
        "gameId": "190203",
        "isFinal": True,
        "halfInnings": [
            {
                "events": [
                    {
                        "playIndex": 27,
                        "situationAfter": {
                            "inning": 9,
                            "half": "bottom",
                            "outs": 3,
                            "score": {"home": 5, "away": 2},
                        },
                    }
                ]
            }
        ],
    }
    findings = validate_no_final_score_leak(payload)
    assert findings, "Scanner should flag situationAfter.score leak"
    messages = " ".join(f.message for f in findings)
    assert "situationAfter.score" in messages


def test_leak_scanner_allows_null_situation_after_score() -> None:
    """A `null` value at `situationAfter.score` is the explicit "stripped"
    sentinel and must not be flagged."""
    from app.scroll_down_mlb.validation import validate_no_final_score_leak

    payload = {
        "gameId": "190203",
        "halfInnings": [
            {
                "events": [
                    {
                        "playIndex": 1,
                        "situationAfter": {
                            "inning": 1,
                            "half": "top",
                            "outs": 1,
                            "score": None,
                        },
                    }
                ]
            }
        ],
    }
    findings = validate_no_final_score_leak(payload)
    nested_findings = [f for f in findings if "situationAfter.score" in f.message]
    assert nested_findings == []


# ---------------------------------------------------------------------------
# scoreChange — wire-safe per-team run delta
# ---------------------------------------------------------------------------


def test_score_change_default_is_zero_zero_for_non_scoring_play() -> None:
    """Non-scoring plays must emit `{home: 0, away: 0}` (never null)."""
    from app.scroll_down_mlb.schemas import HalfInningEvent, ScrollDownEventResult

    event = HalfInningEvent(
        sequence=1,
        play_index=1,
        result=ScrollDownEventResult(label="", description=""),
    )
    dumped = event.model_dump(by_alias=True)
    assert dumped["scoreChange"] == {"home": 0, "away": 0}


def test_score_change_reflects_per_team_delta_for_scoring_play() -> None:
    """A scoring play attributes the run delta to the batting team —
    home delta when bottom inning, away delta when top inning."""
    from app.scroll_down_mlb._dto import _play_card_dto
    from app.scroll_down_mlb.internal_types import BuiltPlayCard

    # Top of the inning: away batting. Solo HR adds 1 to away.
    away_hr = BuiltPlayCard(
        game_id=1,
        play_index=10,
        sort_order=0,
        inning=4,
        inning_half="top",
        inning_label="Top 4th",
        batting_team_abbr="AWY",
        description="Slugger homers.",
        score_before_home=2,
        score_before_away=1,
        score_after_home=2,
        score_after_away=2,
        outs_before=1,
        outs_after=1,
        base_state_before={"first": False, "second": False, "third": False},
        base_state_after={"first": False, "second": False, "third": False},
        runner_names_before={},
        runner_names_after={},
        advances=[],
        event_type="home_run",
    )
    away_card = _play_card_dto(away_hr)
    assert away_card.play is not None
    assert away_card.play.score_change.home == 0
    assert away_card.play.score_change.away == 1

    # Bottom of the inning: home batting. 3-run HR adds 3 to home.
    home_grand_slam = BuiltPlayCard(
        game_id=1,
        play_index=11,
        sort_order=0,
        inning=4,
        inning_half="bottom",
        inning_label="Bot 4th",
        batting_team_abbr="HME",
        description="Slugger triples in three.",
        score_before_home=2,
        score_before_away=2,
        score_after_home=5,
        score_after_away=2,
        outs_before=2,
        outs_after=2,
        base_state_before={"first": True, "second": True, "third": True},
        base_state_after={"first": False, "second": False, "third": False},
        runner_names_before={},
        runner_names_after={},
        advances=[],
        event_type="triple",
    )
    home_card = _play_card_dto(home_grand_slam)
    assert home_card.play is not None
    assert home_card.play.score_change.home == 3
    assert home_card.play.score_change.away == 0


def test_score_change_is_zero_for_non_scoring_play_in_dto() -> None:
    """End-to-end through the DTO conversion: a strikeout produces
    `{home: 0, away: 0}` on the wire."""
    from app.scroll_down_mlb._dto import _play_card_dto
    from app.scroll_down_mlb.internal_types import BuiltPlayCard

    strikeout = BuiltPlayCard(
        game_id=1,
        play_index=5,
        sort_order=0,
        inning=2,
        inning_half="top",
        inning_label="Top 2nd",
        batting_team_abbr="AWY",
        description="Strikes out swinging.",
        score_before_home=0,
        score_before_away=0,
        score_after_home=0,
        score_after_away=0,
        outs_before=1,
        outs_after=2,
        base_state_before={"first": False, "second": False, "third": False},
        base_state_after={"first": False, "second": False, "third": False},
        runner_names_before={},
        runner_names_after={},
        advances=[],
        event_type="strikeout",
    )
    card = _play_card_dto(strikeout)
    assert card.play is not None
    dumped = card.play.model_dump(by_alias=True)
    assert dumped["scoreChange"] == {"home": 0, "away": 0}
    # And the wire still has no `scoreAfter` — `scoreChange` does not
    # collapse into the forbidden cumulative total.
    assert "scoreAfter" not in dumped
