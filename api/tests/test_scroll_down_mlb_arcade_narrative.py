"""Unit tests for the arcade narrative template module."""

from __future__ import annotations

import pytest

from app.scroll_down_mlb.arcade_narrative import (
    ArcadeNarrativeOutput,
    _ArcadeNarrativeContext,
    generate_arcade_narrative,
)


def _ctx(**overrides: object) -> _ArcadeNarrativeContext:
    base = dict(
        inning=9,
        half="bottom",
        outs=1,
        score_margin=0,
        bases_loaded=False,
        runners_on=1,
        batter_last="Soto",
        pitcher_last="Diaz",
        event_type="home_run",
        result_label="Home Run",
        runs_scored=2,
        is_tying=False,
        is_lead_change=True,
        moment_type="hitter",
        difficulty=95,
        pressure_tier="extreme",
    )
    base.update(overrides)
    return _ArcadeNarrativeContext(**base)  # type: ignore[arg-type]


def _all_text_fields(out: ArcadeNarrativeOutput) -> list[str]:
    return [out.headline, out.summary, out.why_this_moment, out.after_reveal]


# ---------------------------------------------------------------------------
# Core contract
# ---------------------------------------------------------------------------


def test_all_four_fields_are_nonempty_for_hitter_moment() -> None:
    out = generate_arcade_narrative(_ctx())
    for field in _all_text_fields(out):
        assert isinstance(field, str)
        assert field.strip()


def test_all_four_fields_are_nonempty_for_pitcher_moment() -> None:
    out = generate_arcade_narrative(
        _ctx(
            moment_type="pitcher",
            half="top",
            inning=8,
            outs=2,
            bases_loaded=True,
            runners_on=3,
            score_margin=1,
            event_type="strikeout",
            result_label="Strikeout",
            runs_scored=0,
            is_tying=False,
            is_lead_change=False,
            difficulty=91,
            pressure_tier="extreme",
        )
    )
    for field in _all_text_fields(out):
        assert isinstance(field, str)
        assert field.strip()


def test_is_pure_function_same_input_same_output() -> None:
    ctx = _ctx()
    a = generate_arcade_narrative(ctx)
    b = generate_arcade_narrative(ctx)
    assert a == b


# ---------------------------------------------------------------------------
# Acceptance criteria: name attribution rules
# ---------------------------------------------------------------------------


def test_hitter_headline_references_batter_last_name() -> None:
    out = generate_arcade_narrative(_ctx(batter_last="Judge"))
    assert "Judge" in out.headline


def test_pitcher_headline_does_not_reference_batter() -> None:
    out = generate_arcade_narrative(
        _ctx(
            moment_type="pitcher",
            half="top",
            inning=8,
            outs=2,
            bases_loaded=True,
            runners_on=3,
            score_margin=1,
            batter_last="Judge",
            pitcher_last="Cole",
            event_type="strikeout",
            result_label="Strikeout",
            runs_scored=0,
            is_lead_change=False,
        )
    )
    assert "Judge" not in out.headline


def test_pitcher_headline_references_escape_situation() -> None:
    out = generate_arcade_narrative(
        _ctx(
            moment_type="pitcher",
            half="top",
            inning=8,
            outs=2,
            bases_loaded=True,
            runners_on=3,
            score_margin=1,
            event_type="strikeout",
            result_label="Strikeout",
            runs_scored=0,
            is_lead_change=False,
        )
    )
    # Bases-loaded two-out escape language is the marquee form.
    headline = out.headline.lower()
    assert "bases loaded" in headline or "no room" in headline


# ---------------------------------------------------------------------------
# Acceptance criteria: tie game produces more dramatic copy than 3-run lead
# ---------------------------------------------------------------------------


_DRAMA_TOKENS = (
    "on the line",
    "walk it off",
    "end it",
    "flip the script",
    "tying run",
    "no room left",
    "needs an escape",
    "escape the jam",
)


def _is_dramatic(headline: str) -> bool:
    lowered = headline.lower()
    return any(token in lowered for token in _DRAMA_TOKENS)


def test_tie_game_is_more_dramatic_than_three_run_lead_for_hitter() -> None:
    tie = generate_arcade_narrative(
        _ctx(
            score_margin=0,
            inning=8,
            half="top",
            runners_on=1,
            bases_loaded=False,
            is_lead_change=False,
        )
    )
    three_run_lead = generate_arcade_narrative(
        _ctx(
            score_margin=3,
            inning=8,
            half="top",
            runners_on=1,
            bases_loaded=False,
            is_lead_change=False,
        )
    )
    assert _is_dramatic(tie.headline)
    assert not _is_dramatic(three_run_lead.headline)
    assert tie.headline != three_run_lead.headline


# ---------------------------------------------------------------------------
# Acceptance criteria scenarios
# ---------------------------------------------------------------------------


def test_walkoff_home_run_scenario_produces_dramatic_hitter_copy() -> None:
    out = generate_arcade_narrative(
        _ctx(
            inning=9,
            half="bottom",
            outs=1,
            score_margin=0,
            bases_loaded=False,
            runners_on=1,
            batter_last="Soto",
            event_type="home_run",
            result_label="Home Run",
            runs_scored=2,
            is_tying=False,
            is_lead_change=True,
            moment_type="hitter",
            difficulty=95,
            pressure_tier="extreme",
        )
    )
    assert "Soto" in out.headline
    assert _is_dramatic(out.headline)
    # Summary should anchor inning + score state.
    assert "9th" in out.summary
    assert "Bottom" in out.summary
    assert "tied" in out.summary.lower()
    # After-reveal should reference the lead change and runs scored.
    after = out.after_reveal.lower()
    assert "soto" in after
    assert "home run" in after
    # why_this_moment should surface the pressure tier.
    assert "extreme" in out.why_this_moment.lower()


def test_strikeout_escape_scenario_produces_pitcher_copy() -> None:
    out = generate_arcade_narrative(
        _ctx(
            inning=8,
            half="top",
            outs=2,
            score_margin=1,
            bases_loaded=True,
            runners_on=3,
            batter_last="Harper",
            pitcher_last="Sale",
            event_type="strikeout",
            result_label="Strikeout",
            runs_scored=0,
            is_tying=False,
            is_lead_change=False,
            moment_type="pitcher",
            difficulty=91,
            pressure_tier="extreme",
        )
    )
    assert "Harper" not in out.headline
    headline = out.headline.lower()
    assert "bases loaded" in headline or "no room" in headline
    # Summary describes the spot from the pitcher's POV.
    assert "Sale" in out.summary
    assert "Top" in out.summary
    assert "8th" in out.summary
    assert "bases loaded" in out.summary.lower()
    # After-reveal should reference the escape, not a damage call.
    after = out.after_reveal.lower()
    assert "sale" in after
    assert "escape" in after or "punches" in after


def test_walk_with_bases_loaded_scenario_forces_run_in() -> None:
    out = generate_arcade_narrative(
        _ctx(
            inning=7,
            half="top",
            outs=1,
            score_margin=2,
            bases_loaded=True,
            runners_on=3,
            batter_last="Betts",
            pitcher_last="Snell",
            event_type="walk",
            result_label="Walk",
            runs_scored=1,
            is_tying=False,
            is_lead_change=False,
            moment_type="pitcher",
            difficulty=78,
            pressure_tier="high",
        )
    )
    # Pitcher headline must not name the batter.
    assert "Betts" not in out.headline
    # After-reveal should call out the forced run.
    after = out.after_reveal.lower()
    assert "snell" in after
    assert "walk" in after
    assert "forced in" in after or "force" in after


# ---------------------------------------------------------------------------
# Guard: no hardcoded team / player names
# ---------------------------------------------------------------------------


_HARDCODED_FORBIDDEN = (
    "Yankees",
    "Dodgers",
    "Red Sox",
    "Mets",
    "Cubs",
    "Aaron",
    "Ohtani",
    "Trout",
)


@pytest.mark.parametrize(
    "ctx",
    [
        _ctx(),
        _ctx(
            moment_type="pitcher",
            half="top",
            inning=8,
            outs=2,
            bases_loaded=True,
            runners_on=3,
            score_margin=1,
            event_type="strikeout",
            result_label="Strikeout",
            runs_scored=0,
            is_lead_change=False,
        ),
        _ctx(
            inning=4,
            half="top",
            outs=0,
            score_margin=5,
            runners_on=0,
            bases_loaded=False,
            event_type="single",
            result_label="Single",
            runs_scored=0,
            is_lead_change=False,
            difficulty=22,
            pressure_tier="low",
        ),
    ],
)
def test_output_contains_no_hardcoded_names(ctx: _ArcadeNarrativeContext) -> None:
    out = generate_arcade_narrative(ctx)
    blob = " ".join(_all_text_fields(out))
    for forbidden in _HARDCODED_FORBIDDEN:
        if forbidden in (ctx.batter_last, ctx.pitcher_last):
            continue
        assert forbidden not in blob


# ---------------------------------------------------------------------------
# Coverage sweep: every supported event_type yields nonempty fields
# ---------------------------------------------------------------------------


_EVENT_TYPES = [
    "walk",
    "hit_by_pitch",
    "strikeout",
    "single",
    "double",
    "triple",
    "home_run",
    "field_out",
    "double_play",
    "triple_play",
    "sacrifice",
    "error",
    "fielders_choice",
    "stolen_base",
    "caught_stealing",
    "pickoff",
    "wild_pitch",
    "passed_ball",
    "balk",
    "catcher_interference",
]


@pytest.mark.parametrize("event_type", _EVENT_TYPES)
@pytest.mark.parametrize("moment_type", ["hitter", "pitcher"])
def test_every_event_type_yields_nonempty_output(
    event_type: str, moment_type: str
) -> None:
    out = generate_arcade_narrative(
        _ctx(
            event_type=event_type,
            result_label=event_type.replace("_", " ").title(),
            moment_type=moment_type,  # type: ignore[arg-type]
            runs_scored=0,
            is_lead_change=False,
            is_tying=False,
        )
    )
    for field in _all_text_fields(out):
        assert field.strip()
