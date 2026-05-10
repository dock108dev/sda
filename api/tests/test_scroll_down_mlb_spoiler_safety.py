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
