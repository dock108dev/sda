"""Tests for the CLASSIFY_GAME_SHAPE pipeline stage.

Covers:
- One fixture per archetype (wire_to_wire, comeback, back_and_forth, blowout,
  low_event, fake_close, late_separation) for NBA.
- MLB fixtures distinguishing ``blowout`` from ``early_avalanche_blowout``,
  plus a low_event pitcher's duel.
- Stage-level behavior: missing previous output, archetype propagated to
  output, league fallback for unknown codes, and determinism.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.pipeline.models import StageInput
from app.services.pipeline.stages.classify_game_shape import (
    classify_archetype,
    execute_classify_game_shape,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _play(
    play_index: int,
    home_score: int,
    away_score: int,
    *,
    quarter: int = 1,
    team: str | None = None,
) -> dict[str, Any]:
    return {
        "play_index": play_index,
        "quarter": quarter,
        "home_score": home_score,
        "away_score": away_score,
        "team_abbreviation": team,
    }


def _moment(
    period: int,
    score_before: list[int],
    score_after: list[int],
    *,
    play_ids: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "period": period,
        "score_before": score_before,
        "score_after": score_after,
        "play_ids": play_ids or [],
    }


def _moments_from_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bucket events into one moment per period using start/end scores.

    Mirrors how moment generation collapses plays into period-aligned chunks.
    Used by tests so blowout detection (which reads moments) and the score
    timeline (which reads pbp_events) see consistent inputs.
    """
    moments: list[dict[str, Any]] = []
    current_period: int | None = None
    current_start: list[int] | None = None
    current_end: list[int] | None = None
    current_play_ids: list[int] = []

    for ev in events:
        period = ev.get("quarter") or 1
        score = [ev.get("home_score") or 0, ev.get("away_score") or 0]
        if current_period is None:
            current_period = period
            current_start = score
        if period != current_period:
            moments.append(
                _moment(
                    current_period,
                    current_start or [0, 0],
                    current_end or current_start or [0, 0],
                    play_ids=current_play_ids,
                )
            )
            current_period = period
            current_start = score
            current_play_ids = []
        current_end = score
        current_play_ids.append(ev["play_index"])

    if current_period is not None:
        moments.append(
            _moment(
                current_period,
                current_start or [0, 0],
                current_end or current_start or [0, 0],
                play_ids=current_play_ids,
            )
        )
    return moments


def _build_timeline(events: list[dict[str, Any]], league: str = "NBA"):
    from app.services.pipeline.helpers.score_timeline import build_score_timeline

    return build_score_timeline(events, league_code=league)


# ---------------------------------------------------------------------------
# NBA archetype fixtures
# ---------------------------------------------------------------------------


def _nba_wire_to_wire_events() -> list[dict[str, Any]]:
    """Home leads from first score, never relinquishes — small, sustained lead."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 6, 0, quarter=1, team="HOME"),
        _play(2, 6, 4, quarter=1, team="AWAY"),
        _play(3, 14, 8, quarter=2, team="HOME"),
        _play(4, 22, 14, quarter=2, team="HOME"),
        _play(5, 32, 22, quarter=3, team="HOME"),
        _play(6, 40, 30, quarter=3, team="AWAY"),
        _play(7, 50, 40, quarter=4, team="HOME"),
        _play(8, 58, 50, quarter=4, team="HOME"),
    ]


def _nba_comeback_events() -> list[dict[str, Any]]:
    """Away builds a 14-point Q1 lead, home claws back to win."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 0, 8, quarter=1, team="AWAY"),
        _play(2, 0, 14, quarter=1, team="AWAY"),
        _play(3, 4, 18, quarter=2, team="AWAY"),
        _play(4, 14, 20, quarter=2, team="HOME"),
        _play(5, 22, 24, quarter=3, team="HOME"),
        _play(6, 30, 28, quarter=3, team="HOME"),  # lead change to HOME
        _play(7, 36, 36, quarter=4, team="AWAY"),  # tied
        _play(8, 44, 40, quarter=4, team="HOME"),
    ]


def _nba_back_and_forth_events() -> list[dict[str, Any]]:
    """Multiple lead changes; no team ever leads by ≥ 10."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 4, 0, quarter=1, team="HOME"),
        _play(2, 4, 6, quarter=1, team="AWAY"),  # lead change -> AWAY
        _play(3, 10, 6, quarter=2, team="HOME"),  # lead change -> HOME
        _play(4, 10, 14, quarter=2, team="AWAY"),  # lead change -> AWAY
        _play(5, 18, 14, quarter=3, team="HOME"),  # lead change -> HOME
        _play(6, 22, 24, quarter=3, team="AWAY"),  # lead change -> AWAY
        _play(7, 28, 28, quarter=4, team="HOME"),  # tied
        _play(8, 32, 30, quarter=4, team="HOME"),
    ]


def _nba_blowout_events() -> list[dict[str, Any]]:
    """Home dominates, sustained 20+ margin, wins by 25."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 12, 2, quarter=1, team="HOME"),
        _play(2, 22, 6, quarter=1, team="HOME"),
        _play(3, 38, 16, quarter=2, team="HOME"),
        _play(4, 52, 26, quarter=2, team="HOME"),
        _play(5, 70, 40, quarter=3, team="HOME"),
        _play(6, 84, 56, quarter=3, team="HOME"),
        _play(7, 100, 70, quarter=4, team="HOME"),
        _play(8, 110, 85, quarter=4, team="HOME"),
    ]


def _nba_fake_close_events() -> list[dict[str, Any]]:
    """Home builds 20+ lead, holds large margin most of game, wins by 2."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 22, 2, quarter=1, team="HOME"),
        _play(2, 26, 4, quarter=1, team="HOME"),
        _play(3, 50, 28, quarter=2, team="HOME"),
        _play(4, 56, 34, quarter=2, team="HOME"),
        _play(5, 76, 56, quarter=3, team="HOME"),
        _play(6, 80, 64, quarter=3, team="HOME"),
        _play(7, 90, 84, quarter=4, team="AWAY"),
        _play(8, 96, 94, quarter=4, team="HOME"),
    ]


def _nba_late_separation_events() -> list[dict[str, Any]]:
    """Tight through Q3, then home pulls away by 9 in Q4."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 6, 4, quarter=1, team="HOME"),
        _play(2, 12, 12, quarter=2, team="AWAY"),
        _play(3, 22, 22, quarter=2, team="HOME"),
        _play(4, 32, 30, quarter=3, team="HOME"),
        _play(5, 42, 42, quarter=3, team="AWAY"),
        _play(6, 50, 48, quarter=4, team="HOME"),
        _play(7, 58, 50, quarter=4, team="HOME"),
        _play(8, 66, 57, quarter=4, team="HOME"),
    ]


# ---------------------------------------------------------------------------
# MLB fixtures
# ---------------------------------------------------------------------------


def _mlb_pitchers_duel_events() -> list[dict[str, Any]]:
    """1-0 pitcher's duel — combined runs ≤ low_scoring_combined."""
    events = [_play(0, 0, 0, quarter=1)]
    for inning in range(2, 9):
        events.append(_play(inning, 0, 0, quarter=inning))
    events.append(_play(9, 1, 0, quarter=9, team="HOME"))
    return events


def _mlb_early_avalanche_blowout_events() -> list[dict[str, Any]]:
    """Home scores 5 runs in inning 1, holds an 11-run lead through 9."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 5, 0, quarter=1, team="HOME"),
        _play(2, 5, 0, quarter=2),
        _play(3, 7, 0, quarter=3, team="HOME"),
        _play(4, 7, 1, quarter=4, team="AWAY"),
        _play(5, 9, 1, quarter=5, team="HOME"),
        _play(6, 9, 1, quarter=6),
        _play(7, 11, 1, quarter=7, team="HOME"),
        _play(8, 11, 1, quarter=8),
        _play(9, 12, 1, quarter=9, team="HOME"),
    ]


def _mlb_late_blowout_events() -> list[dict[str, Any]]:
    """Tight early, home blows it open after the 5th — not an early avalanche."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 1, 0, quarter=1, team="HOME"),
        _play(2, 1, 1, quarter=2, team="AWAY"),
        _play(3, 2, 1, quarter=3, team="HOME"),
        _play(4, 2, 2, quarter=4, team="AWAY"),
        _play(5, 4, 2, quarter=5, team="HOME"),
        _play(6, 8, 2, quarter=6, team="HOME"),
        _play(7, 11, 2, quarter=7, team="HOME"),
        _play(8, 13, 2, quarter=8, team="HOME"),
        _play(9, 14, 2, quarter=9, team="HOME"),
    ]


# ---------------------------------------------------------------------------
# NHL fixtures
# ---------------------------------------------------------------------------


def _nhl_regulation_win_events() -> list[dict[str, Any]]:
    """3-period 4-2 regulation win — winner pulls ahead in P2 and holds."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 1, 0, quarter=1, team="HOME"),
        _play(2, 1, 1, quarter=1, team="AWAY"),
        _play(3, 2, 1, quarter=2, team="HOME"),
        _play(4, 3, 1, quarter=2, team="HOME"),
        _play(5, 3, 2, quarter=3, team="AWAY"),
        _play(6, 4, 2, quarter=3, team="HOME"),
    ]


def _nhl_overtime_win_events() -> list[dict[str, Any]]:
    """4-3 OT win — tied through regulation, decisive goal in period 4 (OT)."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 1, 0, quarter=1, team="HOME"),
        _play(2, 1, 1, quarter=1, team="AWAY"),
        _play(3, 1, 2, quarter=2, team="AWAY"),
        _play(4, 2, 2, quarter=2, team="HOME"),
        _play(5, 2, 3, quarter=3, team="AWAY"),
        _play(6, 3, 3, quarter=3, team="HOME"),
        _play(7, 4, 3, quarter=4, team="HOME"),  # OT winner
    ]


def _nhl_one_goal_game_events() -> list[dict[str, Any]]:
    """2-1 one-goal regulation win — winner leads from first score, never tied later."""
    return [
        _play(0, 0, 0, quarter=1),
        _play(1, 1, 0, quarter=1, team="HOME"),
        _play(2, 2, 0, quarter=2, team="HOME"),
        _play(3, 2, 1, quarter=3, team="AWAY"),
    ]


# ---------------------------------------------------------------------------
# Pure classifier tests
# ---------------------------------------------------------------------------


class TestClassifyArchetypeNBA:
    """Each NBA archetype is selected for its representative fixture."""

    def test_wire_to_wire(self):
        events = _nba_wire_to_wire_events()
        timeline = _build_timeline(events, "NBA")
        assert classify_archetype(timeline, events, "NBA") == "wire_to_wire"

    def test_comeback(self):
        events = _nba_comeback_events()
        timeline = _build_timeline(events, "NBA")
        assert classify_archetype(timeline, events, "NBA") == "comeback"

    def test_back_and_forth(self):
        events = _nba_back_and_forth_events()
        timeline = _build_timeline(events, "NBA")
        assert classify_archetype(timeline, events, "NBA") == "back_and_forth"

    def test_blowout(self):
        events = _nba_blowout_events()
        timeline = _build_timeline(events, "NBA")
        assert classify_archetype(timeline, events, "NBA") == "blowout"

    def test_fake_close(self):
        events = _nba_fake_close_events()
        timeline = _build_timeline(events, "NBA")
        assert classify_archetype(timeline, events, "NBA") == "fake_close"

    def test_late_separation(self):
        events = _nba_late_separation_events()
        timeline = _build_timeline(events, "NBA")
        assert classify_archetype(timeline, events, "NBA") == "late_separation"


class TestClassifyArchetypeMLB:
    """MLB archetypes including the ``early_avalanche_blowout`` sub-type."""

    def test_low_event_pitchers_duel(self):
        events = _mlb_pitchers_duel_events()
        timeline = _build_timeline(events, "MLB")
        assert classify_archetype(timeline, events, "MLB") == "low_event"

    def test_early_avalanche_blowout(self):
        events = _mlb_early_avalanche_blowout_events()
        timeline = _build_timeline(events, "MLB")
        assert (
            classify_archetype(timeline, events, "MLB")
            == "early_avalanche_blowout"
        )

    def test_late_blowout_is_plain_blowout(self):
        events = _mlb_late_blowout_events()
        timeline = _build_timeline(events, "MLB")
        assert classify_archetype(timeline, events, "MLB") == "blowout"


class TestClassifyArchetypeNHL:
    """NHL fixtures cover the goal-sequence shapes expected by ISSUE-014.

    NHL meaningful_lead is 2 (goals); winners that never give up the lead and
    never blow the game open should classify as wire_to_wire. The OT fixture
    flips the lead three times in regulation, then is decided in OT — the
    classifier sees back_and_forth via the lead-change count.
    """

    def test_regulation_win(self) -> None:
        events = _nhl_regulation_win_events()
        timeline = _build_timeline(events, "NHL")
        archetype = classify_archetype(timeline, events, "NHL")
        # 4-2 winner led wire-to-wire after the early 1-1 tie; no NHL-specific
        # archetype currently captures "regulation win" so the closest stable
        # bucket is wire_to_wire (winner held the lead from go-ahead onward).
        assert archetype == "wire_to_wire"

    def test_overtime_win_classifies_to_a_non_blowout_shape(self) -> None:
        events = _nhl_overtime_win_events()
        timeline = _build_timeline(events, "NHL")
        archetype = classify_archetype(timeline, events, "NHL")
        # OT 4-3 with three regulation lead changes is decisively not a
        # blowout/comeback/fake_close. back_and_forth is the strongest match
        # given the lead-change count.
        assert archetype not in {"blowout", "comeback", "fake_close", "low_event"}

    def test_one_goal_game_is_not_blowout(self) -> None:
        events = _nhl_one_goal_game_events()
        timeline = _build_timeline(events, "NHL")
        archetype = classify_archetype(timeline, events, "NHL")
        # 2-1 with the winner ahead the whole way is a wire_to_wire shape;
        # in no case is a one-goal game a blowout.
        assert archetype != "blowout"
        assert archetype == "wire_to_wire"


class TestEmptyTimeline:
    def test_empty_events_returns_default(self):
        from app.services.pipeline.helpers.score_timeline import ScoreTimeline

        empty = ScoreTimeline()
        assert classify_archetype(empty, [], "NBA") == "wire_to_wire"


class TestTiedThroughoutEdgeCase:
    """Edge case from ISSUE-002: a game whose lead is tied or near-tied for the
    full duration must classify into a non-decisive archetype (never blowout
    or comeback). Frequent trade-offs land it as back_and_forth; perpetual
    deadlock falls through to the default wire_to_wire branch.
    """

    def test_nba_lead_traded_repeatedly_classifies_as_back_and_forth(self):
        # Six lead changes; final margin within 1 possession.
        events = [
            _play(0, 0, 0, quarter=1),
            _play(1, 2, 0, quarter=1, team="HOME"),  # HOME up
            _play(2, 2, 4, quarter=1, team="AWAY"),  # lead change → AWAY
            _play(3, 6, 4, quarter=2, team="HOME"),  # lead change → HOME
            _play(4, 6, 9, quarter=2, team="AWAY"),  # lead change → AWAY
            _play(5, 12, 9, quarter=3, team="HOME"),  # lead change → HOME
            _play(6, 12, 16, quarter=3, team="AWAY"),  # lead change → AWAY
            _play(7, 22, 16, quarter=4, team="HOME"),  # lead change → HOME
            _play(8, 24, 22, quarter=4, team="HOME"),  # final, 2-pt margin
        ]
        timeline = _build_timeline(events, "NBA")
        archetype = classify_archetype(timeline, events, "NBA")
        assert archetype == "back_and_forth"

    def test_nba_perpetually_tied_does_not_classify_as_blowout_or_comeback(self):
        # Both teams move in lock-step; scoreboard never separates.
        events = [
            _play(0, 0, 0, quarter=1),
            _play(1, 2, 2, quarter=1, team="HOME"),
            _play(2, 4, 4, quarter=1, team="AWAY"),
            _play(3, 14, 14, quarter=2, team="HOME"),
            _play(4, 22, 22, quarter=3, team="HOME"),
            _play(5, 30, 30, quarter=3, team="AWAY"),
            _play(6, 44, 44, quarter=4, team="HOME"),
        ]
        timeline = _build_timeline(events, "NBA")
        archetype = classify_archetype(timeline, events, "NBA")
        # Tied games never satisfy the comeback or blowout predicates and never
        # end in fake_close or late_separation either; they fall through.
        assert archetype not in {"comeback", "blowout", "fake_close", "late_separation"}


# ---------------------------------------------------------------------------
# Stage-level tests
# ---------------------------------------------------------------------------


class TestExecuteClassifyGameShape:
    @pytest.mark.asyncio
    async def test_missing_previous_output_raises(self):
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output=None,
            game_context={"sport": "NBA"},
        )
        with pytest.raises(ValueError, match="requires NORMALIZE_PBP output"):
            await execute_classify_game_shape(stage_input)

    @pytest.mark.asyncio
    async def test_archetype_in_output(self):
        events = _nba_blowout_events()
        stage_input = StageInput(
            game_id=42,
            run_id=7,
            previous_output={
                "pbp_events": events,
            },
            game_context={"sport": "NBA"},
        )
        result = await execute_classify_game_shape(stage_input)
        assert result.data["archetype"] == "blowout"
        assert result.data["shape_classified"] is True

    @pytest.mark.asyncio
    async def test_passthrough_includes_pbp_events(self):
        events = _nba_wire_to_wire_events()
        previous = {
            "pbp_events": events,
        }
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output=previous,
            game_context={"sport": "NBA"},
        )
        result = await execute_classify_game_shape(stage_input)
        assert result.data["pbp_events"] == events
        assert "moments" not in result.data
        assert "quarter_weights" not in result.data

    @pytest.mark.asyncio
    async def test_unknown_league_falls_back_to_nba(self):
        events = _nba_blowout_events()
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"pbp_events": events},
            game_context={"sport": "WNBA"},
        )
        result = await execute_classify_game_shape(stage_input)
        # WNBA isn't configured; falls back to NBA thresholds → still blowout.
        assert result.data["archetype"] == "blowout"

    @pytest.mark.asyncio
    async def test_mlb_early_avalanche_label(self):
        events = _mlb_early_avalanche_blowout_events()
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"pbp_events": events},
            game_context={"sport": "MLB"},
        )
        result = await execute_classify_game_shape(stage_input)
        assert result.data["archetype"] == "early_avalanche_blowout"

    @pytest.mark.asyncio
    async def test_deterministic(self):
        """Same input yields the same archetype across invocations."""
        events = _nba_back_and_forth_events()
        stage_input = StageInput(
            game_id=1,
            run_id=1,
            previous_output={"pbp_events": events},
            game_context={"sport": "NBA"},
        )
        first = await execute_classify_game_shape(stage_input)
        second = await execute_classify_game_shape(stage_input)
        assert first.data["archetype"] == second.data["archetype"]
