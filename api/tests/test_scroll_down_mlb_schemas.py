"""Schema-level contract tests for Scroll Down MLB.

Locks the wire shape so future refactors can't accidentally:
  * leak `scoreAfter` from PlayPayload
  * drop the camelCase alias generator
  * reintroduce snake_case on the wire
"""

from __future__ import annotations

import pytest

from app.scroll_down_mlb.schemas import (
    BaseState,
    DeckCardType,
    PlayPayload,
    ScoreState,
    ScrollDownMlbDeckCard,
    ScrollDownMlbDeckResponse,
    ScrollDownMlbRecentGame,
    ScrollDownMlbRecentResponse,
    ScrollDownMlbRevealResponse,
    SpoilerPolicy,
    TeamSummary,
    ValidationSeverity,
    ValidationWarning,
)


# ---------------------------------------------------------------------------
# camelCase wire format
# ---------------------------------------------------------------------------


def test_recent_game_serializes_camel_case() -> None:
    game = ScrollDownMlbRecentGame(
        game_id="190203",
        away_team=TeamSummary(id="NYY", abbreviation="NYY", display_name="Yankees"),
        home_team=TeamSummary(id="MIL", abbreviation="MIL", display_name="Brewers"),
        is_final=True,
    )
    dumped = game.model_dump(by_alias=True)
    assert "gameId" in dumped
    assert "awayTeam" in dumped
    assert "homeTeam" in dumped
    assert "isFinal" in dumped
    # No snake_case bleed-through
    assert "game_id" not in dumped
    assert "away_team" not in dumped
    assert "is_final" not in dumped


def test_deck_card_serializes_camel_case() -> None:
    card = ScrollDownMlbDeckCard(
        id="c1",
        type=DeckCardType.play,
        sort_order=1,
        description="x",
        leverage_tier=2,
    )
    dumped = card.model_dump(by_alias=True)
    assert "sortOrder" in dumped
    assert "leverageTier" in dumped


def test_team_summary_color_fields_use_camel_case() -> None:
    team = TeamSummary(
        id="NYY",
        abbreviation="NYY",
        display_name="Yankees",
        color_light="#abc",
        color_dark="#def",
    )
    dumped = team.model_dump(by_alias=True)
    assert dumped["colorLight"] == "#abc"
    assert dumped["colorDark"] == "#def"


# ---------------------------------------------------------------------------
# PlayPayload spoiler invariants
# ---------------------------------------------------------------------------


def test_play_payload_does_not_expose_score_after() -> None:
    """`scoreAfter` would let the final play card leak the final score.
    Guard against re-introducing the field by name."""
    fields = set(PlayPayload.model_fields.keys())
    assert "score_after" not in fields
    # And on the wire (alias)
    payload = PlayPayload(
        play_id="p",
        score_before=ScoreState(home=3, away=2),
        runs_scored_on_play=1,
    ).model_dump(by_alias=True)
    assert "scoreAfter" not in payload
    assert "score_after" not in payload


def test_play_payload_round_trips_score_before_only() -> None:
    payload = PlayPayload(
        play_id="p",
        event_type="single",
        score_before=ScoreState(home=0, away=0),
        runs_scored_on_play=2,
        base_state_before=BaseState(first=True),
    )
    dumped = payload.model_dump(by_alias=True)
    assert dumped["scoreBefore"] == {"home": 0, "away": 0}
    assert dumped["runsScoredOnPlay"] == 2
    assert "scoreAfter" not in dumped


def test_play_payload_emits_score_change_default_zero() -> None:
    """`scoreChange` is non-null on every event — `0/0` for non-scoring
    plays. The renderer combines it with `scoreBefore` to reconstruct
    `scoreAfter` locally without ever reading a cumulative wire total."""
    payload = PlayPayload(
        play_id="p",
        score_before=ScoreState(home=1, away=0),
        runs_scored_on_play=0,
    )
    dumped = payload.model_dump(by_alias=True)
    assert dumped["scoreChange"] == {"home": 0, "away": 0}


def test_play_payload_round_trips_score_change_per_team_delta() -> None:
    from app.scroll_down_mlb.schemas import ScoreChange

    payload = PlayPayload(
        play_id="p",
        score_before=ScoreState(home=2, away=1),
        runs_scored_on_play=2,
        score_change=ScoreChange(home=2, away=0),
    )
    dumped = payload.model_dump(by_alias=True)
    assert dumped["scoreChange"] == {"home": 2, "away": 0}


# ---------------------------------------------------------------------------
# Deck response constraints
# ---------------------------------------------------------------------------


def test_deck_response_spoiler_policy_pinned_to_pre_reveal() -> None:
    """The deck endpoint MUST return spoilerPolicy=pre_reveal — the field
    is typed as Literal so any drift fails type validation."""
    deck = ScrollDownMlbDeckResponse(
        game_id="190203",
        deck_version="v1",
        generated_at="2026-05-09T23:15:00Z",
        is_final=False,
    )
    dumped = deck.model_dump(by_alias=True)
    assert dumped["spoilerPolicy"] == SpoilerPolicy.pre_reveal.value


def test_deck_response_rejects_post_reveal_policy() -> None:
    with pytest.raises(ValueError):
        ScrollDownMlbDeckResponse(
            game_id="190203",
            deck_version="v1",
            generated_at="2026-05-09T23:15:00Z",
            is_final=False,
            spoiler_policy=SpoilerPolicy.post_reveal,  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Reveal payload — final score is allowed here
# ---------------------------------------------------------------------------


def test_reveal_response_exposes_final_score() -> None:
    reveal = ScrollDownMlbRevealResponse(
        game_id="190203",
        final_score={"home": 2, "away": 4},
        winner_team_id="NYY",
    )
    dumped = reveal.model_dump(by_alias=True)
    assert dumped["finalScore"] == {"home": 2, "away": 4}
    assert dumped["winnerTeamId"] == "NYY"


# ---------------------------------------------------------------------------
# Validation findings
# ---------------------------------------------------------------------------


def test_validation_warning_round_trip() -> None:
    finding = ValidationWarning(
        code="home_run_without_score_delta",
        severity=ValidationSeverity.error,
        message="Home run did not increment the score.",
        play_id="abc",
    )
    dumped = finding.model_dump(by_alias=True)
    assert dumped["code"] == "home_run_without_score_delta"
    assert dumped["severity"] == "error"
    assert dumped["playId"] == "abc"


# ---------------------------------------------------------------------------
# Recent response shape
# ---------------------------------------------------------------------------


def test_recent_response_default_is_empty_list() -> None:
    resp = ScrollDownMlbRecentResponse()
    assert resp.games == []
    assert resp.model_dump(by_alias=True) == {"games": []}
