"""Per-module focused tests for the Scroll Down MLB pipeline.

The fixture-driven parity harness in test_scroll_down_mlb_parity.py is the
integration test. These per-module tests pin specific behaviors so a
regression in one module surfaces with a tight, named failure rather than
"some fixture's deck count drifted."
"""

from __future__ import annotations

import pytest

from app.scroll_down_mlb.deck_builder import (
    build_inning_label,
    humanize_description,
    ordinal,
    sample_tier_2,
)
from app.scroll_down_mlb.game_state import (
    compute_timeline,
    inning_half_from_upstream,
    parse_description_advances,
)
from app.scroll_down_mlb.narrative import narrative_for_card
from app.scroll_down_mlb.result_labels import result_chip_label, result_chip_tier
from app.scroll_down_mlb.internal_types import BuiltPlayCard, RunnerAdvance
from app.scroll_down_mlb.visual_mapper import (
    ball_path_from_event,
    classify_animation_profile,
    classify_event,
    compute_leverage_tier,
    outs_delta_for,
)


# ---------------------------------------------------------------------------
# deck_builder
# ---------------------------------------------------------------------------


def test_ordinal_handles_teen_special_cases() -> None:
    assert ordinal(11) == "11th"
    assert ordinal(12) == "12th"
    assert ordinal(13) == "13th"
    assert ordinal(21) == "21st"
    assert ordinal(22) == "22nd"
    assert ordinal(23) == "23rd"


def test_build_inning_label() -> None:
    assert build_inning_label(1, "top") == "Top 1st"
    assert build_inning_label(7, "bottom") == "Bottom 7th"


def test_humanize_description_strips_numbering_and_parens() -> None:
    # The TS humanizer strips numbering + parentheticals + collapses
    # whitespace, but does NOT clean up space-before-period that comes
    # from the parenthetical strip. This test pins the matching behavior.
    out = humanize_description("1. singles to right field (2 RBI).")
    assert out.startswith("Singles to right field")
    assert "RBI" not in out
    assert out.endswith(".")


def test_humanize_description_drops_review_preamble() -> None:
    raw = "Royals challenged (hit by pitch), call on the field was upheld: Singles."
    assert humanize_description(raw) == "Singles."


def test_humanize_description_adds_period_when_missing() -> None:
    assert humanize_description("doubles to left").endswith(".")


def test_sample_tier_2_is_deterministic_per_game_id() -> None:
    pool = [{"playIndex": i} for i in range(10)]
    a = sample_tier_2(pool, 4, game_id=42)
    b = sample_tier_2(pool, 4, game_id=42)
    c = sample_tier_2(pool, 4, game_id=43)
    assert [p["playIndex"] for p in a] == [p["playIndex"] for p in b]
    # Different gameId may pick a different subset.
    assert [p["playIndex"] for p in a] != [p["playIndex"] for p in c] or a == c


def test_sample_tier_2_returns_pool_when_quota_exceeds_size() -> None:
    pool = [{"playIndex": i} for i in range(3)]
    assert sample_tier_2(pool, 10, game_id=1) == pool


# ---------------------------------------------------------------------------
# visual_mapper
# ---------------------------------------------------------------------------


def test_classify_event_uses_explicit_play_type_when_present() -> None:
    assert classify_event({"playType": "HOME_RUN", "description": ""}) == "home_run"
    assert classify_event({"playType": "GIDP", "description": ""}) == "double_play"


def test_classify_event_falls_back_to_description_keywords() -> None:
    assert (
        classify_event({"description": "Singles on a line drive to right field."})
        == "single"
    )
    assert (
        classify_event({"description": "Strikes out swinging."}) == "strikeout"
    )


def test_classify_event_returns_other_for_unmapped_text() -> None:
    assert classify_event({"description": "Mound visit by the manager."}) == "other"


def test_outs_delta_for_event_types() -> None:
    assert outs_delta_for("triple_play") == 3
    assert outs_delta_for("double_play") == 2
    assert outs_delta_for("strikeout") == 1
    assert outs_delta_for("home_run") == 0


def test_ball_path_for_strikeout_is_none() -> None:
    assert ball_path_from_event("strikeout", "Strikes out swinging.") == "none"


def test_ball_path_for_home_run_uses_direction() -> None:
    assert (
        ball_path_from_event("home_run", "homers to left field.") == "home_run_left"
    )


def test_classify_animation_profile_detects_rundown() -> None:
    assert (
        classify_animation_profile("caught_stealing", "Caught in a rundown.")
        == "rundown"
    )


def test_compute_leverage_tier_max_for_late_close_lead_change() -> None:
    tier = compute_leverage_tier(
        inning=9,
        score_before_home=2,
        score_before_away=3,
        score_after_home=4,
        score_after_away=3,
        outs_before=2,
        bases_loaded_before=False,
    )
    assert tier == 2


def test_compute_leverage_tier_zero_for_early_blowout() -> None:
    tier = compute_leverage_tier(
        inning=2,
        score_before_home=0,
        score_before_away=8,
        score_after_home=0,
        score_after_away=8,
        outs_before=0,
        bases_loaded_before=False,
    )
    assert tier == 0


# ---------------------------------------------------------------------------
# game_state
# ---------------------------------------------------------------------------


def test_inning_half_from_upstream_phase_signal() -> None:
    assert inning_half_from_upstream({"phase": "top"}, None) == "top"
    assert inning_half_from_upstream({"phase": "bottom"}, None) == "bottom"


def test_inning_half_from_upstream_period_label() -> None:
    assert inning_half_from_upstream({"periodLabel": "TOP 3"}, None) == "top"
    assert inning_half_from_upstream({"periodLabel": "B 5"}, None) == "bottom"


def test_inning_half_from_upstream_team_fallback() -> None:
    assert (
        inning_half_from_upstream({"teamAbbreviation": "NYY"}, "NYY") == "bottom"
    )
    assert (
        inning_half_from_upstream({"teamAbbreviation": "MIL"}, "NYY") == "top"
    )


def test_inning_half_from_upstream_returns_none_when_unknown() -> None:
    assert inning_half_from_upstream({}, None) is None


def test_parse_description_advances_picks_up_explicit_scoring() -> None:
    advances = parse_description_advances(
        "Goldschmidt scores. Nimmo to 3rd.",
        names_before={"first": "Brandon Nimmo", "third": "Paul Goldschmidt"},
        batter_name="Casey Schmitt",
    )
    # One score advance + one to-3rd advance.
    assert any(a.from_base == "third" and a.to == "home" for a in advances)
    assert any(a.from_base == "first" and a.to == "third" for a in advances)


def test_compute_timeline_propagates_score_across_plays() -> None:
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Smith homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "teamAbbreviation": "AWY",
        },
        {
            "playIndex": 2,
            "quarter": 1,
            "phase": "top",
            "playType": "FIELD_OUT",
            "description": "Lines out to second.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 1},
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    assert timeline[1].is_scoring_play
    assert timeline[1].runs_scored == 1
    assert timeline[2].score_before_away == 1
    assert not timeline[2].is_scoring_play


# ---------------------------------------------------------------------------
# result_labels + narrative
# ---------------------------------------------------------------------------


def _card(**overrides) -> BuiltPlayCard:
    base: dict = dict(
        game_id=1,
        play_index=1,
        sort_order=0,
        inning=1,
        inning_half="top",
        inning_label="Top 1st",
        batting_team_abbr="AWY",
        description="",
        score_before_home=0,
        score_before_away=0,
        score_after_home=0,
        score_after_away=0,
        outs_before=0,
        outs_after=0,
        base_state_before={"first": False, "second": False, "third": False},
        base_state_after={"first": False, "second": False, "third": False},
        runner_names_before={},
        runner_names_after={},
        advances=[],
        event_type=None,
    )
    base.update(overrides)
    return BuiltPlayCard(**base)


def test_result_chip_label_strikeout_called_third() -> None:
    card = _card(
        event_type="strikeout",
        description="Smith called out on strikes.",
        outs_after=1,
    )
    label = result_chip_label(card)
    assert label.primary == "CALLED STRIKE THREE"


def test_result_chip_label_home_run_with_grand_slam() -> None:
    card = _card(
        event_type="home_run",
        description="Smith hits a grand slam.",
        score_after_home=4,
        score_after_away=0,
        inning_half="bottom",
        advances=[RunnerAdvance(from_base="home", to="home")],
    )
    label = result_chip_label(card)
    assert label.primary == "GRAND SLAM"


def test_result_chip_tier_home_run_is_max() -> None:
    card = _card(
        event_type="home_run",
        description="Solo shot.",
        score_after_home=1,
        inning_half="bottom",
        advances=[RunnerAdvance(from_base="home", to="home")],
    )
    assert result_chip_tier(card) == 3


def test_narrative_walk_loads_the_bases() -> None:
    card = _card(
        event_type="walk",
        description="Walks.",
        base_state_before={"first": True, "second": True, "third": False},
        base_state_after={"first": True, "second": True, "third": True},
        batter_name="Joe Smith",
        advances=[RunnerAdvance(from_base="home", to="first")],
    )
    text = narrative_for_card(card)
    assert text is not None
    assert "load the bases" in text


def test_narrative_returns_none_when_event_type_missing() -> None:
    card = _card(event_type=None)
    assert narrative_for_card(card) is None


def test_narrative_strikeout_with_pitcher_attribution() -> None:
    card = _card(
        event_type="strikeout",
        description="Strikes out.",
        outs_before=2,
        outs_after=3,
        batter_name="Joe Smith",
        pitcher_name="Max Fried",
    )
    text = narrative_for_card(card)
    assert text is not None
    assert "Fried" in text
    assert "Smith" in text
