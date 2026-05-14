"""Per-module focused tests for the Scroll Down MLB pipeline.

The fixture-driven parity harness in test_scroll_down_mlb_parity.py is the
integration test. These per-module tests pin specific behaviors so a
regression in one module surfaces with a tight, named failure rather than
"some fixture's deck count drifted."
"""

from __future__ import annotations

import pytest

from app.scroll_down_mlb.deck_builder import (
    _name_from_description,
    _name_from_player_dict,
    _name_string,
    build_inning_label,
    humanize_description,
    ordinal,
    sample_tier_2,
    to_play_card,
)
from app.scroll_down_mlb._classify import build_event_result, classify_reveal_type
from app.scroll_down_mlb.game_state import (
    _group_into_containers,
    compute_timeline,
    inning_half_from_upstream,
    parse_description_advances,
    summarize_half_innings,
)
from app.scroll_down_mlb.internal_types import BuiltPlayCard, RunnerAdvance, TimelineEntry
from app.scroll_down_mlb.narrative import narrative_for_card
from app.scroll_down_mlb.result_labels import result_chip_label, result_chip_tier
from app.scroll_down_mlb._advances import build_base_movements
from app.scroll_down_mlb._state_readers import (
    normalize_runner_label,
    read_upstream_runner_names,
)
from app.scroll_down_mlb.schemas import (
    BaseMovement,
    BasesSituation,
    GameSituation,
    GameSituationAfter,
    RunnerSummary,
    ScoreSituation,
    TeamSummary,
)
from app.scroll_down_mlb.visual_mapper import (
    ball_path_from_event,
    classify_animation_profile,
    classify_event,
    compute_leverage_tier,
    display_hint_fields,
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


# ---------------------------------------------------------------------------
# Overlay-correction regressions: each test pins one previously-wrong case
# from the visual_mapper analysis. Names describe the case, not an issue id.
# ---------------------------------------------------------------------------


def test_caught_stealing_home_emits_throw_path_not_none() -> None:
    # A caught-stealing-at-home involves a real throw; the overlay must
    # surface a path so the renderer can draw the arc instead of nothing.
    result = ball_path_from_event(
        "caught_stealing",
        "Jorge Lopez caught stealing home, thrown out by the catcher.",
    )
    assert result != "none"
    assert result.startswith("ground_")


def test_caught_stealing_second_still_pathless() -> None:
    # Non-home caught stealings keep the existing pathless behaviour.
    assert (
        ball_path_from_event(
            "caught_stealing", "Smith caught stealing second base."
        )
        == "none"
    )


def test_strikeout_with_wild_pitch_uses_pitch_path() -> None:
    # Dropped third strike: the ball got past the catcher, so the overlay
    # should reflect the pitch trajectory rather than suppressing entirely.
    assert (
        ball_path_from_event(
            "strikeout", "Strikes out swinging, wild pitch, reaches first."
        )
        == "pitch"
    )


def test_strikeout_with_passed_ball_uses_pitch_path() -> None:
    assert (
        ball_path_from_event(
            "strikeout", "Strikes out looking, passed ball, runner to second."
        )
        == "pitch"
    )


def test_strikeout_swinging_still_pathless() -> None:
    assert ball_path_from_event("strikeout", "Strikes out swinging.") == "none"


def test_pickoff_with_rundown_uses_rundown_profile() -> None:
    # The rundown guard previously omitted pickoff, so the runner animated
    # as a stolen-base attempt instead of zig-zagging.
    assert (
        classify_animation_profile(
            "pickoff", "Picked off first, rundown, tagged out."
        )
        == "rundown"
    )


def test_throwing_error_routes_to_throw_destination_not_pitcher_mound() -> None:
    # A throwing error to first should surface ground_1b — the previous
    # fallback was ground_p, which drew the ball back to the mound.
    assert (
        ball_path_from_event(
            "error",
            "Reaches on a throwing error by the third baseman, throws wildly to first.",
        )
        == "ground_1b"
    )


def test_single_with_grounder_keyword_classifies_as_grounder() -> None:
    # The outfield-direction check used to run first and return fly_lf for
    # a description that explicitly described a grounder through the hole.
    result = ball_path_from_event(
        "single", "Singles to left, ground ball through the hole."
    )
    assert result.startswith("ground_")


def test_single_with_only_direction_still_goes_outfield() -> None:
    assert (
        ball_path_from_event("single", "Singles to left field.") == "fly_lf"
    )


def test_ground_zone_strips_relay_throw_destination() -> None:
    # "First baseman throws to second" used to return ground_1b because
    # the first fielder mentioned was the throwing fielder. The relay
    # stripper now removes "throws to second" so 1B remains the source.
    # We assert via the public ball_path_from_event with a field_out event
    # — _ground_zone is exercised through the grounder branch.
    assert (
        ball_path_from_event(
            "field_out",
            "Grounder fielded by the shortstop, throws to first for the out.",
        )
        == "ground_ss"
    )


def test_ground_zone_relay_throw_does_not_promote_throw_target() -> None:
    # Crafted to make sure the relay-throw destination ("to first") does
    # not bubble up to the fielder match. The third baseman is the actual
    # fielder; the throw is to first.
    assert (
        ball_path_from_event(
            "field_out",
            "Ground ball to third baseman, throws to first.",
        )
        == "ground_3b"
    )


def test_strikeout_keyword_does_not_match_player_initial() -> None:
    # The bare \bk\b shorthand was removed because it matched player-name
    # initials like "K. Martinez". Without explicit strikeout phrasing,
    # this description must not classify as a strikeout.
    assert classify_event({"description": "K. Martinez grounds out."}) != "strikeout"


def test_double_keyword_does_not_match_double_switch() -> None:
    # "Double switch" is a lineup move, not a two-base hit.
    assert (
        classify_event({"description": "Manager makes a double switch."}) != "double"
    )


def test_double_keyword_does_not_match_double_header() -> None:
    assert (
        classify_event({"description": "Game two of the double header begins."})
        != "double"
    )


def test_display_hint_fields_flags_batted_ball_for_single_to_left() -> None:
    show, loc, suppress = display_hint_fields("single", "fly_lf", "shallow_fly")
    assert show is True
    assert loc == "fly_lf"
    assert suppress is False


def test_display_hint_fields_suppresses_for_strikeout_with_wild_pitch() -> None:
    # Strikeout retains "pitch" as ball_path now, but the overlay must
    # stay suppressed (it's a pitch path, not a batted-ball arc).
    show, loc, suppress = display_hint_fields("strikeout", "pitch", "strikeout")
    assert show is False
    assert suppress is True


def test_display_hint_fields_suppresses_for_caught_stealing_throw_home() -> None:
    # Throw path is surfaced for analytics (hit_location) but the
    # batted-ball overlay is suppressed.
    show, loc, suppress = display_hint_fields(
        "caught_stealing", "ground_p", "stolen_base"
    )
    assert show is False
    assert loc == "ground_p"
    assert suppress is True


def test_display_hint_fields_none_for_walk() -> None:
    show, loc, suppress = display_hint_fields("walk", "none", "walk")
    assert show is False
    assert loc is None
    assert suppress is True


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
# _state_readers — normalize_runner_label
# ---------------------------------------------------------------------------


def test_normalize_runner_label_full_first_last() -> None:
    assert normalize_runner_label("Julio Rodriguez") == "J RODRIGUEZ"


def test_normalize_runner_label_strips_period_after_initial() -> None:
    assert normalize_runner_label("C. Carroll") == "C CARROLL"


def test_normalize_runner_label_hyphenated_first_takes_first_char() -> None:
    # Multi-part first names use only the first token's first character.
    assert normalize_runner_label("Jo-El Rodriguez") == "J RODRIGUEZ"


def test_normalize_runner_label_two_token_short_first_name() -> None:
    assert normalize_runner_label("Bo Bichette") == "B BICHETTE"


def test_normalize_runner_label_none_passes_through() -> None:
    assert normalize_runner_label(None) is None


def test_normalize_runner_label_empty_string_passes_through() -> None:
    assert normalize_runner_label("") == ""


def test_normalize_runner_label_whitespace_only_passes_through() -> None:
    # `.strip()` reduces whitespace-only to empty; treat as empty.
    assert normalize_runner_label("   ") == ""


def test_normalize_runner_label_already_initial_form_idempotent() -> None:
    assert normalize_runner_label("C CARROLL") == "C CARROLL"
    assert normalize_runner_label("c carroll") == "C CARROLL"


def test_normalize_runner_label_hyphenated_last_name_preserves_hyphen() -> None:
    assert normalize_runner_label("Bo Smith-Jones") == "B SMITH-JONES"


def test_normalize_runner_label_multi_word_first_name() -> None:
    # First token's first character drives the initial, last token is the last name.
    assert normalize_runner_label("Bobby Joe Smith") == "B SMITH"


def test_normalize_runner_label_single_token_uppercased() -> None:
    assert normalize_runner_label("Rodriguez") == "RODRIGUEZ"


def test_normalize_runner_label_dotted_double_initial_takes_first() -> None:
    # "C.J. Wilson" — first initial only per the issue rule.
    assert normalize_runner_label("C.J. Wilson") == "C WILSON"


def test_read_upstream_runner_names_applies_normalization_to_dict_form() -> None:
    names = read_upstream_runner_names(
        {"first": "Julio Rodriguez", "second": "C. Carroll"}
    )
    assert names == {"first": "J RODRIGUEZ", "second": "C CARROLL"}


def test_read_upstream_runner_names_applies_normalization_to_list_form() -> None:
    names = read_upstream_runner_names(
        [
            {"base": "1", "name": "Bo Bichette"},
            {"base": "3", "runnerName": "Jo-El Rodriguez"},
        ]
    )
    assert names == {"first": "B BICHETTE", "third": "J RODRIGUEZ"}


def test_read_upstream_runner_names_applies_normalization_to_nested_dict_form() -> None:
    names = read_upstream_runner_names(
        {"first": {"name": "Corbin Carroll"}, "third": {"playerName": "Gabriel Moreno"}}
    )
    assert names == {"first": "C CARROLL", "third": "G MORENO"}


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
# Deterministic before/after GameSituation snapshots
# ---------------------------------------------------------------------------


def test_compute_timeline_populates_situation_before_and_after() -> None:
    """Every TimelineEntry carries a `situation_before` and `situation_after`.

    `situation_before.score` mirrors the running pre-play score (safe —
    already public via prior cards). `situation_after` uses the score-less
    `GameSituationAfter` type per the spoiler-safety contract — the final
    play's score must not be readable from the post-play snapshot.
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Smith homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "ballsBefore": 2,
            "strikesBefore": 1,
            "teamAbbreviation": "AWY",
            "outsAfter": 0,
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    entry = timeline[1]
    assert entry.situation_before is not None
    assert entry.situation_after is not None
    assert entry.situation_before.inning == 1
    assert entry.situation_before.half == "top"
    assert entry.situation_before.outs == 0
    assert entry.situation_before.score is not None
    assert entry.situation_before.score.home == 0
    assert entry.situation_before.score.away == 0
    # Count from upstream `ballsBefore`/`strikesBefore`.
    assert entry.situation_before.count is not None
    assert entry.situation_before.count.balls == 2
    assert entry.situation_before.count.strikes == 1
    # situation_after uses GameSituationAfter, which structurally excludes
    # `score` per the spoiler-safety contract — accessing the attribute
    # is a type error.
    assert not hasattr(entry.situation_after, "score")


def test_compute_timeline_carries_count_across_mid_pa_pitches() -> None:
    """A sequence of pitches within a PA accumulates the running count.

    Upstream provides post-pitch `balls`/`strikes` on each pitch event;
    `situation_before.count` mirrors the prior pitch's `situation_after.count`,
    starting at 0-0 at the top of the PA.
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "PITCH",
            "description": "Strike one, swinging.",
            "balls": 0,
            "strikes": 1,
            "teamAbbreviation": "AWY",
        },
        {
            "playIndex": 2,
            "quarter": 1,
            "phase": "top",
            "playType": "PITCH",
            "description": "Strike two, called.",
            "balls": 0,
            "strikes": 2,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")

    first = timeline[1]
    assert first.situation_before.count is not None
    assert first.situation_before.count.balls == 0
    assert first.situation_before.count.strikes == 0
    assert first.situation_after.count is not None
    assert first.situation_after.count.balls == 0
    assert first.situation_after.count.strikes == 1

    second = timeline[2]
    assert second.situation_before.count is not None
    assert second.situation_before.count.balls == 0
    assert second.situation_before.count.strikes == 1
    assert second.situation_after.count is not None
    assert second.situation_after.count.balls == 0
    assert second.situation_after.count.strikes == 2


def test_compute_timeline_strikeout_clears_count_after() -> None:
    """A PA-terminating event surfaces the pre-pitch count on
    `situation_before`, but `situation_after.count` is `None` because the
    count is no longer applicable once the batter has been retired.
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "STRIKEOUT",
            "description": "Strikes out swinging.",
            # The 3-2 count entering the strikeout pitch. Either
            # explicit `*Before` keys (used here) or a sequence of
            # pitch events would have left the running count tracker
            # at (3, 2).
            "ballsBefore": 3,
            "strikesBefore": 2,
            "outsAfter": 1,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    entry = timeline[1]
    assert entry.situation_before.count is not None
    assert entry.situation_before.count.balls == 3
    assert entry.situation_before.count.strikes == 2
    # PA over → no meaningful post-play count on the wire.
    assert entry.situation_after.count is None


def test_compute_timeline_count_is_null_when_upstream_omits_count() -> None:
    """When upstream supplies no count keys for a play, both
    `situation_before.count` and `situation_after.count` are `None` —
    the implementation never guesses a fallback count.
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "SINGLE",
            "description": "Lines a single to right.",
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    entry = timeline[1]
    assert entry.situation_before.count is None
    assert entry.situation_after.count is None


def test_compute_timeline_compounding_outs_error_does_not_double_count() -> None:
    """Scenario A from research/before-state-upstream-vs-inferred.md.

    A mislabeled event type (FIELD_OUT carrying a real double-play
    outcome) used to drift the outs accumulator: heuristic delta = 1
    when the truth was 2. When upstream provides `outsAfter`, the
    deterministic snapshot must trust the upstream value rather than
    the event-based heuristic, so the next play's `outs_before`
    reflects the real state.
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            # Real outcome was a double play; feed mislabels it as a
            # plain field out. `outs_delta_for("field_out")` returns 1.
            "playType": "FIELD_OUT",
            "description": "Grounds into the 6-4-3 double play.",
            # Upstream knows the truth: 2 outs after this play.
            "outsAfter": 2,
            "teamAbbreviation": "AWY",
        },
        {
            "playIndex": 2,
            "quarter": 1,
            "phase": "top",
            "playType": "STRIKEOUT",
            "description": "Strikes out.",
            "outsAfter": 3,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    # Play 1 honored the upstream outsAfter (2), not the event heuristic (1).
    assert timeline[1].outs_after == 2
    assert timeline[1].situation_after.outs == 2
    # Play 2's before-outs reflects the corrected running state, not
    # the heuristic delta — the deterministic snapshot does not
    # double-count outs from the mislabeled event.
    assert timeline[2].outs_before == 2
    assert timeline[2].situation_before.outs == 2
    # The half rotates after the third out without leaking state.
    assert timeline[2].outs_after == 3


def test_compute_timeline_ignores_ambiguous_runners_key_as_before_state() -> None:
    """Scenario B from research/before-state-upstream-vs-inferred.md.

    Some vendor feeds emit `runners` as the post-play snapshot. The
    deterministic before-state reader must not consume that as the
    pre-play state — it falls back to the prior play's
    `situation_after.bases` (which here is the empty starting state).
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "SINGLE",
            "description": "Singles to right.",
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
            # Vendor emits `runners` as POST-play snapshot. If the
            # reader treated it as before-state, the play would appear
            # to start with a runner on first.
            "runners": [{"base": "1", "name": "PostPlayRunner"}],
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    bases_before = timeline[1].situation_before.bases
    # The ambiguous `runners` field was NOT read as before-state.
    assert bases_before.first is None
    assert bases_before.second is None
    assert bases_before.third is None
    # And the legacy occupancy mirror agrees.
    assert timeline[1].base_state_before == {
        "first": False,
        "second": False,
        "third": False,
    }


def test_compute_timeline_skips_pointsscored_attribution_when_unknown() -> None:
    """Scenario C from research/before-state-upstream-vs-inferred.md.

    When the only score signal is `pointsScored` and there is no
    `scoringTeamAbbr` nor a known `home_team_abbr`, attribution by
    half-inning is unsafe (corrupts every downstream score_before).
    The deterministic implementation drops the score change rather
    than guess.
    """
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            # `phase` is the only half signal; if it were also missing
            # the team heuristic in `inning_half_from_upstream` would
            # also be unavailable. We provide it so the test isolates
            # the points-scored attribution issue specifically.
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Smith homers.",
            "pointsScored": 1,
            # Critically: no scoreBefore/score keys, no scoringTeamAbbr,
            # and the caller passes home_team_abbr=None below.
        },
        {
            "playIndex": 2,
            "quarter": 1,
            "phase": "top",
            "playType": "STRIKEOUT",
            "description": "Strikes out.",
            "outsAfter": 1,
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr=None)
    # The score change is dropped — neither side was credited.
    assert timeline[1].score_after_home == 0
    assert timeline[1].score_after_away == 0
    assert timeline[1].situation_before.score is not None
    assert timeline[1].situation_before.score.home == 0
    assert timeline[1].situation_before.score.away == 0
    # And the running score stays clean for the next play.
    assert timeline[2].score_before_home == 0
    assert timeline[2].score_before_away == 0
    assert timeline[2].situation_before.score is not None
    assert timeline[2].situation_before.score.home == 0
    assert timeline[2].situation_before.score.away == 0


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


# ---------------------------------------------------------------------------
# deck_builder — batter / pitcher name resolution
# ---------------------------------------------------------------------------


def test_name_string_returns_trimmed_or_none() -> None:
    assert _name_string("  Aaron Judge ") == "Aaron Judge"
    assert _name_string("") is None
    assert _name_string("   ") is None
    assert _name_string(None) is None
    assert _name_string(42) is None


def test_name_from_player_dict_pulls_name_field() -> None:
    assert _name_from_player_dict({"id": 1, "name": "Aaron Judge"}) == "Aaron Judge"
    assert _name_from_player_dict({"id": 1, "name": None}) is None
    assert _name_from_player_dict({"id": 1}) is None
    # Tolerates bare-string legacy payloads.
    assert _name_from_player_dict("Aaron Judge") == "Aaron Judge"
    assert _name_from_player_dict(None) is None


def test_name_from_description_parses_leading_proper_noun_phrase() -> None:
    assert (
        _name_from_description("Aaron Judge homers on a fly ball to center field.")
        == "Aaron Judge"
    )
    assert (
        _name_from_description("Vladimir Guerrero Jr. doubles down the line.")
        == "Vladimir Guerrero Jr"
    )
    assert (
        _name_from_description("Bo Bichette grounds into a 6-4-3 double play.")
        == "Bo Bichette"
    )
    # Already-lowercase first token — no name to recover.
    assert _name_from_description("a wild pitch advances the runner.") is None
    # Empty / falsy.
    assert _name_from_description("") is None
    assert _name_from_description(None) is None


def _make_frame() -> TimelineEntry:
    situation_before = GameSituation(
        inning=1,
        half="top",
        outs=0,
        score=ScoreSituation(home=0, away=0),
        count=None,
        bases=BasesSituation(),
    )
    situation_after = GameSituationAfter(
        inning=1,
        half="top",
        outs=0,
        count=None,
        bases=BasesSituation(),
    )
    return TimelineEntry(
        play_index=1,
        inning=1,
        half="top",
        outs_before=0,
        outs_after=0,
        score_before_home=0,
        score_before_away=0,
        score_after_home=0,
        score_after_away=1,
        base_state_before={"first": False, "second": False, "third": False},
        base_state_after={"first": False, "second": False, "third": False},
        runner_names_before={},
        runner_names_after={},
        advances=[],
        event_type="home_run",
        runs_scored=1,
        is_scoring_play=True,
        is_tying_play=False,
        is_lead_change_play=False,
        is_late_leverage=False,
        half_from_upstream=True,
        situation_before=situation_before,
        situation_after=situation_after,
    )


def test_to_play_card_recovers_batter_from_raw_data_dict() -> None:
    """The scraper writes raw_data['batter']={'id', 'name'}; the deck
    builder used to short-circuit on the dict and lose the name."""
    play = {
        "playIndex": 1,
        "description": "Aaron Judge homers on a fly ball to center field.",
        "batter": {"id": 100, "name": "Aaron Judge"},
        # playerName explicitly None — simulates the regression where the
        # normalized DB column came in null but raw_data still had the
        # batter dict.
        "playerName": None,
    }
    card = to_play_card(game_id=1, sort_order=0, play=play, frame=_make_frame())
    assert card.batter_name == "Aaron Judge"


def test_to_play_card_falls_back_to_description_when_all_else_null() -> None:
    play = {
        "playIndex": 1,
        "description": "Aaron Judge homers on a fly ball to center field.",
        "batter": {"id": 100, "name": None},
        "playerName": None,
    }
    card = to_play_card(game_id=1, sort_order=0, play=play, frame=_make_frame())
    assert card.batter_name == "Aaron Judge"


def test_to_play_card_pulls_pitcher_from_per_play_raw_data() -> None:
    """pitcher_of_record only comes from MLBPitcherGameStats which is
    populated post-game. For a live game, raw_data['pitcher']['name']
    is the only source and the deck builder must read it."""
    play = {
        "playIndex": 1,
        "description": "Aaron Judge homers on a fly ball to center field.",
        "batter": {"id": 100, "name": "Aaron Judge"},
        "pitcher": {"id": 200, "name": "Freddy Peralta"},
    }
    card = to_play_card(
        game_id=1,
        sort_order=0,
        play=play,
        frame=_make_frame(),
        pitcher_of_record=None,
        home_probable_pitcher=None,
        away_probable_pitcher=None,
    )
    assert card.pitcher_name == "Freddy Peralta"


def test_to_play_card_prefers_pitcher_of_record_over_raw_data() -> None:
    play = {
        "playIndex": 1,
        "description": "Aaron Judge homers on a fly ball to center field.",
        "batter": {"id": 100, "name": "Aaron Judge"},
        "pitcher": {"id": 200, "name": "Some Scraped Name"},
    }
    card = to_play_card(
        game_id=1,
        sort_order=0,
        play=play,
        frame=_make_frame(),
        pitcher_of_record="Freddy Peralta",
    )
    assert card.pitcher_name == "Freddy Peralta"


# ---------------------------------------------------------------------------
# Pitcher running stat snapshots
# ---------------------------------------------------------------------------


def test_pitcher_stat_snapshot_innings_pitched_format() -> None:
    from app.scroll_down_mlb._pitcher_timeline import PitcherStatSnapshot

    snap = PitcherStatSnapshot(
        name="X", outs=13, hits=5, walks=2, strikeouts=6, runs=2, home_runs=1,
    )
    assert snap.innings_pitched == "4.1"
    assert snap.format_compact() == "4.1 IP · 6 K · 2 BB · 2 R"


def test_pitcher_stat_snapshot_zero_outs() -> None:
    from app.scroll_down_mlb._pitcher_timeline import PitcherStatSnapshot

    snap = PitcherStatSnapshot(
        name="X", outs=0, hits=0, walks=0, strikeouts=0, runs=0, home_runs=0,
    )
    assert snap.innings_pitched == "0.0"


def test_compute_pitcher_stat_snapshots_accumulates_per_pitcher() -> None:
    from app.scroll_down_mlb._pitcher_timeline import (
        compute_pitcher_stat_snapshots,
        compute_pitcher_timeline,
    )

    plays = [
        # Pitcher A faces 3 batters: K, BB, single. 1 out, 1 H, 1 BB, 1 K.
        # runsScoredOnPlay carries the per-play delta. Score-delta against a
        # missing scoreBefore used to count the cumulative tally on every
        # play; that fallback was removed (produced "7 R" after one run).
        {"playIndex": 1, "playType": "STRIKEOUT", "description": "Strikes out.",
         "pitcher": {"id": 1, "name": "A"}, "teamAbbreviation": "AWY",
         "runsScoredOnPlay": 0},
        {"playIndex": 2, "playType": "WALK", "description": "Walks.",
         "pitcher": {"id": 1, "name": "A"}, "teamAbbreviation": "AWY",
         "runsScoredOnPlay": 0},
        {"playIndex": 3, "playType": "SINGLE", "description": "Singles.",
         "pitcher": {"id": 1, "name": "A"}, "teamAbbreviation": "AWY",
         "runsScoredOnPlay": 0},
        # Pitcher B takes over: gives up an HR (1 R), then another out.
        {"playIndex": 4, "playType": "HOME_RUN", "description": "Homers.",
         "pitcher": {"id": 2, "name": "B"}, "teamAbbreviation": "AWY",
         "runsScoredOnPlay": 1},
        {"playIndex": 5, "playType": "FIELD_OUT", "description": "Grounds out.",
         "pitcher": {"id": 2, "name": "B"}, "teamAbbreviation": "AWY",
         "runsScoredOnPlay": 0},
    ]
    pitcher_timeline = compute_pitcher_timeline(plays, None, "Home", "Away", "HME")
    snaps = compute_pitcher_stat_snapshots(plays, pitcher_timeline)

    # Pitcher A through play 3.
    assert snaps[3].name == "A"
    assert snaps[3].outs == 1
    assert snaps[3].hits == 1
    assert snaps[3].walks == 1
    assert snaps[3].strikeouts == 1
    assert snaps[3].home_runs == 0
    assert snaps[3].runs == 0

    # Pitcher B resets the accumulators (different name = different bucket).
    assert snaps[4].name == "B"
    assert snaps[4].outs == 0
    assert snaps[4].hits == 1
    assert snaps[4].home_runs == 1
    assert snaps[4].runs == 1

    # Pitcher B's next play continues their accumulator.
    assert snaps[5].name == "B"
    assert snaps[5].outs == 1
    assert snaps[5].runs == 1  # No new run on this play.


def test_compute_pitcher_stat_snapshots_skips_plays_with_no_pitcher() -> None:
    from app.scroll_down_mlb._pitcher_timeline import (
        compute_pitcher_stat_snapshots,
        compute_pitcher_timeline,
    )

    plays = [
        {"playIndex": 1, "playType": "STRIKEOUT", "description": "Strikes out.",
         # No pitcher field at all → timeline returns None → snapshot skipped.
         "teamAbbreviation": "AWY"},
    ]
    timeline = compute_pitcher_timeline(plays, None, "Home", "Away", "HME")
    snaps = compute_pitcher_stat_snapshots(plays, timeline)
    assert 1 not in snaps


def test_compute_pitcher_timeline_prefers_per_play_over_boxscore() -> None:
    """The per-play matchup pitcher is the live source — boxscore-derived
    fallbacks should never override it."""
    from app.scroll_down_mlb._pitcher_timeline import compute_pitcher_timeline

    plays = [
        {"playIndex": 1, "playType": "STRIKEOUT", "description": "Strikes out.",
         "pitcher": {"id": 1, "name": "Live Pitcher"}, "teamAbbreviation": "AWY"},
    ]
    pitchers = [
        {"team": "Home", "playerName": "Boxscore Pitcher",
         "inningsPitched": "1.0", "isStarter": True},
    ]
    timeline = compute_pitcher_timeline(plays, pitchers, "Home", "Away", "HME")
    assert timeline[1] == "Live Pitcher"


# ---------------------------------------------------------------------------
# Half-inning container grouping
# ---------------------------------------------------------------------------


def _three_inning_plays() -> list[dict]:
    """A 3-half-inning game with a complete 3rd-out for each half. The
    last play of each half forces outs to 3, which lets `compute_timeline`
    rotate the half cleanly via its post-commit boundary check.
    """
    return [
        # Top 1 — three outs.
        {"playIndex": 1, "quarter": 1, "phase": "top",
         "playType": "STRIKEOUT", "description": "Strikes out.",
         "outsAfter": 1, "teamAbbreviation": "AWY"},
        {"playIndex": 2, "quarter": 1, "phase": "top",
         "playType": "FIELD_OUT", "description": "Grounds out.",
         "outsAfter": 2, "teamAbbreviation": "AWY"},
        {"playIndex": 3, "quarter": 1, "phase": "top",
         "playType": "FIELD_OUT", "description": "Flies out.",
         "outsAfter": 3, "teamAbbreviation": "AWY"},
        # Bottom 1 — single + two outs.
        {"playIndex": 4, "quarter": 1, "phase": "bottom",
         "playType": "SINGLE", "description": "Singles to right.",
         "outsAfter": 0, "teamAbbreviation": "HME"},
        {"playIndex": 5, "quarter": 1, "phase": "bottom",
         "playType": "FIELD_OUT", "description": "Pops out.",
         "outsAfter": 1, "teamAbbreviation": "HME"},
        {"playIndex": 6, "quarter": 1, "phase": "bottom",
         "playType": "DOUBLE_PLAY", "description": "Grounds into double play.",
         "outsAfter": 3, "teamAbbreviation": "HME"},
        # Top 2 — home run + two outs.
        {"playIndex": 7, "quarter": 2, "phase": "top",
         "playType": "HOME_RUN", "description": "Smith homers.",
         "score": {"home": 0, "away": 1},
         "scoreBefore": {"home": 0, "away": 0},
         "outsAfter": 0, "teamAbbreviation": "AWY"},
        {"playIndex": 8, "quarter": 2, "phase": "top",
         "playType": "STRIKEOUT", "description": "Strikes out.",
         "outsAfter": 1, "teamAbbreviation": "AWY"},
        {"playIndex": 9, "quarter": 2, "phase": "top",
         "playType": "FIELD_OUT", "description": "Lines out.",
         "outsAfter": 2, "teamAbbreviation": "AWY"},
        {"playIndex": 10, "quarter": 2, "phase": "top",
         "playType": "FIELD_OUT", "description": "Grounds out.",
         "outsAfter": 3, "teamAbbreviation": "AWY"},
    ]


def _teams() -> tuple[TeamSummary, TeamSummary]:
    home = TeamSummary(id="1", abbreviation="HME", display_name="Homes")
    away = TeamSummary(id="2", abbreviation="AWY", display_name="Aways")
    return home, away


def test_group_into_containers_three_half_innings_with_sequences() -> None:
    plays = _three_inning_plays()
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=123,
        timeline=timeline,
        selected_play_indices={1, 7, 10},
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )

    # Three half-innings: (1, top), (1, bottom), (2, top).
    assert [(c.inning, c.half) for c in containers] == [
        (1, "top"),
        (1, "bottom"),
        (2, "top"),
    ]

    # Top 1: away batting, home fielding. 1-based sequence within the half.
    c0 = containers[0]
    assert c0.batting_team.abbreviation == "AWY"
    assert c0.fielding_team.abbreviation == "HME"
    assert [e.sequence for e in c0.events] == [1, 2, 3]
    assert [e.play_index for e in c0.events] == [1, 2, 3]
    # Selection overlay: only play 1 was selected in this half.
    assert c0.selected_play_indices == [1]
    assert c0.events[0].is_selected is True
    assert c0.events[1].is_selected is False

    # Bottom 1: home batting, away fielding.
    c1 = containers[1]
    assert c1.batting_team.abbreviation == "HME"
    assert c1.fielding_team.abbreviation == "AWY"
    assert [e.sequence for e in c1.events] == [1, 2, 3]
    assert c1.selected_play_indices == []  # nothing selected in this half

    # Top 2: includes the home run; meta should carry scored_runs through.
    c2 = containers[2]
    assert c2.batting_team.abbreviation == "AWY"
    assert [e.sequence for e in c2.events] == [1, 2, 3, 4]
    assert c2.selected_play_indices == [7, 10]
    assert c2.meta.scored_runs == 1
    assert c2.meta.had_activity is True


def test_group_into_containers_partial_last_half_inning_is_open() -> None:
    """A live game with an in-progress half — no inning-end signal yet."""
    plays = [
        {"playIndex": 1, "quarter": 1, "phase": "top",
         "playType": "STRIKEOUT", "description": "Strikes out.",
         "outsAfter": 1, "teamAbbreviation": "AWY"},
        {"playIndex": 2, "quarter": 1, "phase": "top",
         "playType": "FIELD_OUT", "description": "Grounds out.",
         "outsAfter": 2, "teamAbbreviation": "AWY"},
        # No third out, no inning-2 plays — half is still open.
        {"playIndex": 3, "quarter": 1, "phase": "top",
         "playType": "SINGLE", "description": "Singles.",
         "outsAfter": 2, "teamAbbreviation": "AWY"},
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=42,
        timeline=timeline,
        selected_play_indices=set(),
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )

    assert len(containers) == 1
    only = containers[0]
    assert (only.inning, only.half) == (1, "top")
    assert [e.sequence for e in only.events] == [1, 2, 3]
    # Last event in the open half is not the third out.
    assert only.events[-1].outs_after == 2
    assert only.meta.had_activity is True


def test_group_into_containers_sorts_top_before_bottom() -> None:
    """Containers are ordered (inning, top→bottom), not by half name alphabetically."""
    plays = _three_inning_plays()
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=1,
        timeline=timeline,
        selected_play_indices=set(),
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )

    # Confirm the top→bottom ordering within inning 1 (would be reversed
    # if we sorted halves lexicographically — "bottom" < "top").
    inning_1 = [c for c in containers if c.inning == 1]
    assert [c.half for c in inning_1] == ["top", "bottom"]


# ---------------------------------------------------------------------------
# BaseMovement diff (build_base_movements)
# ---------------------------------------------------------------------------


def test_base_movement_runner_advances_first_to_second() -> None:
    advances = [RunnerAdvance(from_base="first", to="second")]
    bases_before = BasesSituation(first=RunnerSummary(name="Smith"))
    movements = build_base_movements(advances, bases_before, batter=None)
    assert len(movements) == 1
    only = movements[0]
    assert only.from_base == "first"
    assert only.to_base == "second"
    assert only.style == "advance"
    assert only.out_at is None
    assert only.runner.name == "Smith"
    assert only.reason == "base_changed"


def test_base_movement_runner_scores() -> None:
    advances = [RunnerAdvance(from_base="third", to="home")]
    bases_before = BasesSituation(third=RunnerSummary(name="Jones"))
    movements = build_base_movements(advances, bases_before, batter=None)
    assert len(movements) == 1
    only = movements[0]
    assert only.from_base == "third"
    assert only.to_base == "home"
    assert only.style == "score"
    assert only.out_at is None
    assert only.runner.name == "Jones"
    assert only.reason == "scored"


def test_base_movement_runner_out_at_second() -> None:
    advances = [RunnerAdvance(from_base="first", to="out", out_at="second")]
    bases_before = BasesSituation(first=RunnerSummary(name="Wilson"))
    movements = build_base_movements(advances, bases_before, batter=None)
    assert len(movements) == 1
    only = movements[0]
    assert only.to_base == "out"
    assert only.style == "out"
    assert only.out_at == "second"
    assert only.runner.name == "Wilson"
    assert only.reason == "runner_out"


def test_base_movement_runner_holds_emits_nothing() -> None:
    # Held runners are absent from `advances` — diff_advances/predict_advances
    # never emit a same-base entry. The diff helper therefore produces no
    # BaseMovement for them either.
    bases_before = BasesSituation(third=RunnerSummary(name="Jones"))
    movements = build_base_movements([], bases_before, batter=None)
    assert movements == []


def test_base_movement_double_play_emits_each_runner_out_with_out_at() -> None:
    # Bases-loaded grounder DP-style: lead runners are forced. The batter
    # putout (from=home, to=out) is filtered — its in-place flare is
    # animation-profile driven, not a movement record.
    advances = [
        RunnerAdvance(from_base="second", to="out", out_at="third"),
        RunnerAdvance(from_base="first", to="out", out_at="second"),
        RunnerAdvance(from_base="home", to="out", out_at="first"),
    ]
    bases_before = BasesSituation(
        first=RunnerSummary(name="Smith"),
        second=RunnerSummary(name="Jones"),
    )
    movements = build_base_movements(
        advances, bases_before, batter=RunnerSummary(name="Batter")
    )
    assert len(movements) == 2
    assert all(m.style == "out" for m in movements)
    by_from = {m.from_base: m for m in movements}
    assert by_from["second"].out_at == "third"
    assert by_from["second"].runner.name == "Jones"
    assert by_from["first"].out_at == "second"
    assert by_from["first"].runner.name == "Smith"
    # Batter putout was filtered.
    assert "home" not in by_from


def test_base_movement_walk_emits_batter_and_pushed_runner() -> None:
    # Walk with runner on first: batter takes first; pushed runner forced
    # to second. Two BaseMovements, batter's is synthetic (from=home).
    advances = [
        RunnerAdvance(from_base="first", to="second"),
        RunnerAdvance(from_base="home", to="first"),
    ]
    bases_before = BasesSituation(first=RunnerSummary(name="Pushed"))
    movements = build_base_movements(
        advances, bases_before, batter=RunnerSummary(name="Walker")
    )
    assert len(movements) == 2
    by_from = {m.from_base: m for m in movements}
    # Batter — synthetic from=home.
    assert by_from["home"].to_base == "first"
    assert by_from["home"].style == "advance"
    assert by_from["home"].runner.name == "Walker"
    assert by_from["home"].reason == "batter_reached"
    # Pushed runner.
    assert by_from["first"].to_base == "second"
    assert by_from["first"].style == "advance"
    assert by_from["first"].runner.name == "Pushed"
    assert by_from["first"].reason == "base_changed"


def test_base_movement_solo_hr_emits_only_batter_score() -> None:
    # Solo HR: the batter never appears in situation_after.bases, but
    # still emits a synthetic from=home, to=home movement.
    advances = [RunnerAdvance(from_base="home", to="home")]
    bases_before = BasesSituation()
    movements = build_base_movements(
        advances, bases_before, batter=RunnerSummary(name="Slugger")
    )
    assert len(movements) == 1
    only = movements[0]
    assert only.from_base == "home"
    assert only.to_base == "home"
    assert only.style == "score"
    assert only.runner.name == "Slugger"
    assert only.reason == "scored"


def test_base_movement_filters_strikeout_batter_putout() -> None:
    # Strikeout / batter force out — no BaseMovement emitted (the in-place
    # flare is profile-driven, not a movement record).
    advances = [RunnerAdvance(from_base="home", to="out")]
    movements = build_base_movements(
        advances, BasesSituation(), batter=RunnerSummary(name="Striker")
    )
    assert movements == []


def test_base_movement_serializes_camel_case_aliases() -> None:
    movement = BaseMovement(
        runner=RunnerSummary(name="Smith"),
        from_base="first",
        to_base="second",
        style="advance",
        out_at=None,
        reason="base_changed",
    )
    dumped = movement.model_dump(by_alias=True)
    assert "fromBase" in dumped
    assert "toBase" in dumped
    assert "outAt" in dumped
    assert dumped["fromBase"] == "first"
    assert dumped["toBase"] == "second"


def test_compute_timeline_attaches_movements_for_solo_home_run() -> None:
    """End-to-end: a solo HR fed through compute_timeline lands a single
    BaseMovement on the entry (batter, from=home, to=home, style=score) and
    the post-play bases are empty (batter never appears on a base)."""
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Slugger homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "batterName": "Slugger",
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    entry = timeline[1]
    hr_moves = [
        m for m in entry.movements
        if m.from_base == "home" and m.to_base == "home"
    ]
    assert len(hr_moves) == 1
    assert hr_moves[0].style == "score"
    assert hr_moves[0].runner.name == "Slugger"
    bases_after = entry.situation_after.bases
    assert bases_after.first is None
    assert bases_after.second is None
    assert bases_after.third is None


def test_group_into_containers_threads_movements_into_half_inning_events() -> None:
    """The HalfInningEvent surface mirrors entry.movements end-to-end."""
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Slugger homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "batterName": "Slugger",
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=99,
        timeline=timeline,
        selected_play_indices={1},
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )
    event = containers[0].events[0]
    assert any(
        m.from_base == "home" and m.to_base == "home" and m.style == "score"
        for m in event.movements
    )
    dumped = containers[0].model_dump(by_alias=True)
    movement_dump = dumped["events"][0]["movements"][0]
    assert "fromBase" in movement_dump
    assert "toBase" in movement_dump


def test_group_into_containers_serializes_camel_case() -> None:
    """The container DTO must surface camelCase aliases on the wire."""
    plays = _three_inning_plays()[:3]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=7,
        timeline=timeline,
        selected_play_indices={1},
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )
    dumped = containers[0].model_dump(by_alias=True)
    assert "gameId" in dumped
    assert "battingTeam" in dumped
    assert "fieldingTeam" in dumped
    assert "selectedPlayIndices" in dumped
    assert dumped["events"][0]["isSelected"] is True
    assert "scoreBefore" in dumped["events"][0]
    # Forbidden spoiler keys must not appear.
    assert "scoreAfter" not in dumped["events"][0]


def test_half_inning_event_score_change_zero_for_non_scoring_play() -> None:
    """A strikeout produces a zero `scoreChange` on the HalfInningEvent."""
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "STRIKEOUT",
            "description": "Strikes out swinging.",
            "outsAfter": 1,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=11,
        timeline=timeline,
        selected_play_indices=set(),
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )
    event = containers[0].events[0]
    assert event.score_change.home == 0
    assert event.score_change.away == 0
    dumped = containers[0].model_dump(by_alias=True)
    assert dumped["events"][0]["scoreChange"] == {"home": 0, "away": 0}


def test_half_inning_event_score_change_attributes_run_to_batting_team() -> None:
    """Top-of-inning HR credits the away delta, not the home delta."""
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Smith homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=12,
        timeline=timeline,
        selected_play_indices={1},
        half_meta=half_meta,
        home_team=home,
        away_team=away,
    )
    event = containers[0].events[0]
    assert event.score_change.home == 0
    assert event.score_change.away == 1


def test_half_inning_event_situation_after_has_no_score_field() -> None:
    """The internal `situation_after` snapshot uses `GameSituationAfter`,
    which structurally excludes `score`. Even if a future schema change
    surfaced `situation_after` on the wire, the post-play cumulative
    score could not leak."""
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Smith homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    entry = timeline[1]
    assert not hasattr(entry.situation_after, "score")
    # And the field is also absent from the serialized form.
    dumped = entry.situation_after.model_dump(by_alias=True)
    assert "score" not in dumped


# ---------------------------------------------------------------------------
# revealType classification + result flags + matchup population
# ---------------------------------------------------------------------------


def test_classify_reveal_type_pitch_level_events() -> None:
    assert classify_reveal_type("ball") == "pitch"
    assert classify_reveal_type("called_strike") == "pitch"
    assert classify_reveal_type("swinging_strike") == "pitch"
    assert classify_reveal_type("foul") == "pitch"
    assert classify_reveal_type("wild_pitch") == "pitch"


def test_classify_reveal_type_plate_appearance_events() -> None:
    assert classify_reveal_type("strikeout") == "plate_appearance"
    assert classify_reveal_type("walk") == "plate_appearance"
    assert classify_reveal_type("hit_by_pitch") == "plate_appearance"
    assert classify_reveal_type("single") == "plate_appearance"
    assert classify_reveal_type("double") == "plate_appearance"
    assert classify_reveal_type("home_run") == "plate_appearance"
    assert classify_reveal_type("field_out") == "plate_appearance"


def test_classify_reveal_type_multi_runner_or_fielding_plays() -> None:
    assert classify_reveal_type("double_play") == "play"
    assert classify_reveal_type("triple_play") == "play"
    assert classify_reveal_type("sacrifice") == "play"
    assert classify_reveal_type("fielders_choice") == "play"
    assert classify_reveal_type("caught_stealing") == "play"
    assert classify_reveal_type("pickoff") == "play"
    assert classify_reveal_type("stolen_base") == "play"


def test_classify_reveal_type_unknown_falls_back_to_play() -> None:
    assert classify_reveal_type(None) == "play"
    assert classify_reveal_type("") == "play"
    assert classify_reveal_type("other") == "play"


def test_event_result_is_scoring_play_for_run_scoring_event() -> None:
    """A run-scoring event flips `is_scoring_play=True` regardless of which
    team scored — the flag tracks the cumulative-runs delta."""
    result = build_event_result(
        event_type="single",
        description="Singles, scoring a run.",
        outs_after=1,
        score_change_home=0,
        score_change_away=1,
    )
    assert result.is_scoring_play is True
    assert result.is_hit is True
    assert result.is_out is False

    # Bottom-of-the-inning scoring still flips the flag.
    bottom = build_event_result(
        event_type="single",
        description="Singles, scoring a run.",
        outs_after=1,
        score_change_home=1,
        score_change_away=0,
    )
    assert bottom.is_scoring_play is True


def test_event_result_is_inning_ending_on_third_out() -> None:
    """`is_inning_ending` mirrors `situation_after.outs == 3`."""
    third_out = build_event_result(
        event_type="strikeout",
        description="Strikes out swinging.",
        outs_after=3,
        score_change_home=0,
        score_change_away=0,
    )
    assert third_out.is_inning_ending is True
    assert third_out.is_strikeout is True
    assert third_out.is_out is True

    not_yet = build_event_result(
        event_type="strikeout",
        description="Strikes out swinging.",
        outs_after=2,
        score_change_home=0,
        score_change_away=0,
    )
    assert not_yet.is_inning_ending is False
    assert not_yet.is_strikeout is True


def test_event_result_is_out_covers_all_putout_event_types() -> None:
    """`is_out` is true for any event that produced at least one out."""
    putouts = [
        "strikeout",
        "field_out",
        "double_play",
        "triple_play",
        "sacrifice",
        "fielders_choice",
        "caught_stealing",
        "pickoff",
    ]
    for event in putouts:
        result = build_event_result(
            event_type=event,
            description="",
            outs_after=1,
            score_change_home=0,
            score_change_away=0,
        )
        assert result.is_out is True, f"expected is_out=True for {event}"


def test_event_result_walk_and_hit_flags() -> None:
    walk = build_event_result(
        event_type="walk",
        description="Walks.",
        outs_after=0,
        score_change_home=0,
        score_change_away=0,
    )
    assert walk.is_walk is True
    assert walk.is_out is False
    assert walk.is_hit is False
    assert walk.label == "WALK"

    homer = build_event_result(
        event_type="home_run",
        description="Slugger homers.",
        outs_after=0,
        score_change_home=0,
        score_change_away=1,
    )
    assert homer.is_hit is True
    assert homer.is_scoring_play is True
    assert homer.label == "HOME RUN"


def test_container_event_carries_reveal_type_and_result() -> None:
    """End-to-end: a single home-run play surfaces revealType,
    `result.is_scoring_play`, and a populated matchup on the container."""
    plays = [
        {
            "playIndex": 1,
            "quarter": 1,
            "phase": "top",
            "playType": "HOME_RUN",
            "description": "Julio Rodriguez homers.",
            "score": {"home": 0, "away": 1},
            "scoreBefore": {"home": 0, "away": 0},
            "batterName": "Julio Rodriguez",
            "outsAfter": 0,
            "teamAbbreviation": "AWY",
        },
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    plays_by_index = {1: plays[0]}
    pitcher_by_play = {1: "Spencer Strider"}
    containers = _group_into_containers(
        game_id=42,
        timeline=timeline,
        selected_play_indices={1},
        half_meta=half_meta,
        home_team=home,
        away_team=away,
        plays_by_index=plays_by_index,
        pitcher_by_play=pitcher_by_play,
    )
    event = containers[0].events[0]
    assert event.reveal_type == "plate_appearance"
    assert event.result.is_hit is True
    assert event.result.is_scoring_play is True
    assert event.result.is_inning_ending is False
    assert event.result.label == "HOME RUN"
    assert event.matchup.batter is not None
    assert event.matchup.batter.name == "J RODRIGUEZ"
    assert event.matchup.pitcher is not None
    assert event.matchup.pitcher.name == "S STRIDER"


def test_container_event_third_out_marks_inning_ending() -> None:
    plays = [
        {"playIndex": 1, "quarter": 1, "phase": "top",
         "playType": "STRIKEOUT", "description": "Strikes out.",
         "batterName": "Bo Bichette",
         "outsAfter": 1, "teamAbbreviation": "AWY"},
        {"playIndex": 2, "quarter": 1, "phase": "top",
         "playType": "FIELD_OUT", "description": "Grounds out.",
         "outsAfter": 2, "teamAbbreviation": "AWY"},
        {"playIndex": 3, "quarter": 1, "phase": "top",
         "playType": "FIELD_OUT", "description": "Lines out.",
         "outsAfter": 3, "teamAbbreviation": "AWY"},
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()
    plays_by_index = {int(p["playIndex"]): p for p in plays}

    containers = _group_into_containers(
        game_id=1,
        timeline=timeline,
        selected_play_indices=set(),
        half_meta=half_meta,
        home_team=home,
        away_team=away,
        plays_by_index=plays_by_index,
        pitcher_by_play={},
    )
    events = containers[0].events
    assert events[0].result.is_inning_ending is False
    assert events[1].result.is_inning_ending is False
    assert events[2].result.is_inning_ending is True
    # First-event matchup gets normalized — "Bo Bichette" -> "B BICHETTE".
    assert events[0].matchup.batter is not None
    assert events[0].matchup.batter.name == "B BICHETTE"
    # Pitcher omitted upstream → matchup.pitcher is None.
    assert events[0].matchup.pitcher is None


def test_container_event_matchup_null_when_upstream_omits_names() -> None:
    """When upstream omits batter/pitcher, the matchup fields are None."""
    plays = [
        {"playIndex": 1, "quarter": 1, "phase": "top",
         "playType": "STRIKEOUT", "description": "Strikes out.",
         "outsAfter": 1, "teamAbbreviation": "AWY"},
    ]
    timeline = compute_timeline(plays, home_team_abbr="HME")
    half_meta = summarize_half_innings(timeline.values())
    home, away = _teams()

    containers = _group_into_containers(
        game_id=1,
        timeline=timeline,
        selected_play_indices=set(),
        half_meta=half_meta,
        home_team=home,
        away_team=away,
        plays_by_index={1: plays[0]},
        pitcher_by_play={1: None},
    )
    event = containers[0].events[0]
    assert event.matchup.batter is None
    assert event.matchup.pitcher is None
    # Wire serialization preserves the explicit nulls.
    dumped = containers[0].model_dump(by_alias=True)
    assert dumped["events"][0]["matchup"] == {"batter": None, "pitcher": None}
    assert dumped["events"][0]["revealType"] == "plate_appearance"
    assert dumped["events"][0]["result"]["isStrikeout"] is True
