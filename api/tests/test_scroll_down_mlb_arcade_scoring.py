"""Unit tests for the pure arcade pressure/difficulty scoring module."""

from __future__ import annotations

import pytest

from app.scroll_down_mlb.arcade_scoring import (
    approximate_wpa,
    difficulty_score,
    pressure_tier,
)

_EMPTY_BASES: dict[str, bool] = {"first": False, "second": False, "third": False}


def _bases(*occupied: str) -> dict[str, bool]:
    return {base: base in occupied for base in ("first", "second", "third")}


# ---------------------------------------------------------------------------
# difficulty_score
# ---------------------------------------------------------------------------


def test_difficulty_score_low_leverage_routine_floor() -> None:
    # leverage_tier=0 + inning <= 4 + no runners — even with 0 outs, the
    # only situational bonus is outs_remaining * 2 = 4, keeping the
    # result well under 35 per the acceptance bound.
    score = difficulty_score(
        inning=3,
        half="top",
        outs_before=0,
        base_state_before=_EMPTY_BASES,
        score_margin=4,
        leverage_tier=0,
        is_tying_play=False,
        is_lead_change_play=False,
        is_late_leverage=False,
    )
    assert score <= 35


def test_difficulty_score_low_leverage_with_two_outs_no_runners() -> None:
    score = difficulty_score(
        inning=4,
        half="bottom",
        outs_before=2,
        base_state_before=_EMPTY_BASES,
        score_margin=5,
        leverage_tier=0,
        is_tying_play=False,
        is_lead_change_play=False,
        is_late_leverage=False,
    )
    assert score <= 35


def test_difficulty_score_climactic_tying_late_inning_clears_eighty() -> None:
    score = difficulty_score(
        inning=9,
        half="bottom",
        outs_before=1,
        base_state_before=_EMPTY_BASES,
        score_margin=1,
        leverage_tier=2,
        is_tying_play=True,
        is_lead_change_play=False,
        is_late_leverage=False,
    )
    assert score >= 80


def test_difficulty_score_caps_at_one_hundred() -> None:
    score = difficulty_score(
        inning=12,
        half="bottom",
        outs_before=0,
        base_state_before=_bases("first", "second", "third"),
        score_margin=0,
        leverage_tier=2,
        is_tying_play=True,
        is_lead_change_play=True,
        is_late_leverage=True,
    )
    assert score == 100


def test_difficulty_score_treats_none_leverage_as_routine() -> None:
    a = difficulty_score(
        inning=5,
        half="top",
        outs_before=1,
        base_state_before=_EMPTY_BASES,
        score_margin=2,
        leverage_tier=None,
        is_tying_play=False,
        is_lead_change_play=False,
        is_late_leverage=False,
    )
    b = difficulty_score(
        inning=5,
        half="top",
        outs_before=1,
        base_state_before=_EMPTY_BASES,
        score_margin=2,
        leverage_tier=0,
        is_tying_play=False,
        is_lead_change_play=False,
        is_late_leverage=False,
    )
    assert a == b


def test_difficulty_score_walkoff_homer_scenario_is_extreme() -> None:
    # Mirrors the BRAINDUMP hitter example: 9th-bottom, runner on second,
    # tie game broken by a walk-off home run. The formula should produce
    # an "extreme" tier score for this profile.
    score = difficulty_score(
        inning=9,
        half="bottom",
        outs_before=1,
        base_state_before=_bases("second"),
        score_margin=0,
        leverage_tier=2,
        is_tying_play=False,
        is_lead_change_play=True,
        is_late_leverage=True,
    )
    assert pressure_tier(score) == "extreme"


def test_difficulty_score_bases_loaded_escape_scenario_is_extreme() -> None:
    # Mirrors the BRAINDUMP pitcher example: 8th-top, bases loaded, two
    # outs, one-run game. High-stakes escape spot.
    score = difficulty_score(
        inning=8,
        half="top",
        outs_before=2,
        base_state_before=_bases("first", "second", "third"),
        score_margin=1,
        leverage_tier=2,
        is_tying_play=False,
        is_lead_change_play=False,
        is_late_leverage=True,
    )
    assert pressure_tier(score) == "extreme"


# ---------------------------------------------------------------------------
# pressure_tier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (0, "low"),
        (39, "low"),
        (40, "medium"),
        (64, "medium"),
        (65, "high"),
        (79, "high"),
        # BRAINDUMP hitter-example difficulty value — covers the
        # documented tier alignment.
        (87, "high"),
        (89, "high"),
        (90, "extreme"),
        # BRAINDUMP pitcher-example difficulty value.
        (91, "extreme"),
        (100, "extreme"),
    ],
)
def test_pressure_tier_boundaries(value: int, expected: str) -> None:
    assert pressure_tier(value) == expected


# ---------------------------------------------------------------------------
# approximate_wpa
# ---------------------------------------------------------------------------


def test_approximate_wpa_returns_clamped_values_with_nonnegative_delta() -> None:
    before, after, delta = approximate_wpa(
        difficulty=87,
        runs_scored=2,
        is_scoring_play=True,
        is_tying_play=False,
        is_lead_change_play=True,
    )
    for value in (before, after, delta):
        assert 0.0 <= value <= 1.0
    assert delta >= 0.0
    assert after >= before


def test_approximate_wpa_defensive_escape_still_swings() -> None:
    # BRAINDUMP pitcher example — no runs scored, no tying/lead change,
    # but the leverage of the spot should still produce a non-trivial
    # WPA swing for the recap narrative.
    before, after, delta = approximate_wpa(
        difficulty=91,
        runs_scored=0,
        is_scoring_play=False,
        is_tying_play=False,
        is_lead_change_play=False,
    )
    assert 0.0 <= before <= 1.0
    assert 0.0 <= after <= 1.0
    assert delta > 0.0


def test_approximate_wpa_walkoff_pushes_after_to_one() -> None:
    # Walk-off-style: big lead-change + multi-run play at high leverage
    # should saturate wpaAfter at 1.0.
    _before, after, delta = approximate_wpa(
        difficulty=95,
        runs_scored=2,
        is_scoring_play=True,
        is_tying_play=False,
        is_lead_change_play=True,
    )
    assert after == pytest.approx(1.0)
    assert delta >= 0.0


def test_approximate_wpa_lead_change_delta_exceeds_routine_scoring() -> None:
    _, _, lead_change_delta = approximate_wpa(
        difficulty=70,
        runs_scored=1,
        is_scoring_play=True,
        is_tying_play=False,
        is_lead_change_play=True,
    )
    _, _, routine_delta = approximate_wpa(
        difficulty=70,
        runs_scored=1,
        is_scoring_play=True,
        is_tying_play=False,
        is_lead_change_play=False,
    )
    assert lead_change_delta > routine_delta


def test_approximate_wpa_handles_zero_difficulty_and_negative_runs() -> None:
    before, after, delta = approximate_wpa(
        difficulty=0,
        runs_scored=-1,
        is_scoring_play=False,
        is_tying_play=False,
        is_lead_change_play=False,
    )
    for value in (before, after, delta):
        assert 0.0 <= value <= 1.0
    assert delta >= 0.0
