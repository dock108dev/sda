"""Arcade narrative templates.

Companion to ``narrative.py`` but tuned for the arcade daily pressure
pack rather than the spoiler-free catch-up feed.

Produces four short, deterministic text fields per moment:

* ``headline`` — the marquee one-liner shown before reveal.
* ``summary`` — a one-sentence situation recap (inning, base state, score).
* ``why_this_moment`` — why this play is in today's pack (leverage / pressure).
* ``after_reveal`` — what happened, in narrative voice, referencing the
  outcome label produced by ``result_labels.py``.

Strict rule preserved from ``narrative.py``: every clause must be
supported by data on the supplied context. No invented stadium reactions,
pitch types, or unattributed commentary.

Pure functions only — no DB access, no I/O. Inputs are caller-prepared
scalars; the caller is responsible for trimming ``batter_last`` /
``pitcher_last`` to last-name-only form (see ``_last_name_only`` in
``narrative.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MomentType = Literal["hitter", "pitcher"]


@dataclass(frozen=True)
class _ArcadeNarrativeContext:
    inning: int
    half: str
    outs: int
    score_margin: int
    bases_loaded: bool
    runners_on: int
    batter_last: str
    pitcher_last: str
    event_type: str
    result_label: str
    runs_scored: int
    is_tying: bool
    is_lead_change: bool
    moment_type: MomentType
    difficulty: int
    pressure_tier: str


@dataclass(frozen=True)
class ArcadeNarrativeOutput:
    headline: str
    summary: str
    why_this_moment: str
    after_reveal: str


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_HALF_LABEL = {"top": "Top", "bottom": "Bottom"}


def _ordinal(n: int) -> str:
    suffix = (
        "th"
        if 10 <= (n % 100) <= 20
        else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    )
    return f"{n}{suffix}"


def _half_phrase(half: str, inning: int) -> str:
    label = _HALF_LABEL.get(half, half.capitalize() if half else "Top")
    return f"{label} of the {_ordinal(inning)}"


def _outs_phrase(outs: int) -> str:
    if outs == 0:
        return "no outs"
    if outs == 1:
        return "one out"
    return "two outs"


def _runners_phrase(runners_on: int, bases_loaded: bool) -> str:
    if bases_loaded:
        return "bases loaded"
    if runners_on == 0:
        return "bases empty"
    if runners_on == 1:
        return "a runner aboard"
    return "two on"


def _margin_phrase(margin: int, moment_type: MomentType) -> str:
    """Render the score gap from the moment-actor's perspective.

    ``score_margin`` is unsigned in the contract; the verbiage just
    needs to communicate the tightness of the spot.
    """
    if margin == 0:
        return "tied"
    if margin == 1:
        return "in a one-run game"
    if margin == 2:
        return "in a two-run game"
    if moment_type == "hitter":
        return "down by a few" if margin <= 4 else "facing a wide gap"
    return "with a multi-run cushion"


def _is_walkoff_setup(ctx: _ArcadeNarrativeContext) -> bool:
    return (
        ctx.moment_type == "hitter"
        and ctx.half == "bottom"
        and ctx.inning >= 9
        and ctx.score_margin <= 1
    )


# ---------------------------------------------------------------------------
# Headline templates
# ---------------------------------------------------------------------------


def _hitter_headline(ctx: _ArcadeNarrativeContext) -> str:
    batter = ctx.batter_last
    if _is_walkoff_setup(ctx):
        if ctx.bases_loaded:
            return f"{batter} steps in with the bases loaded and a chance to walk it off"
        return f"{batter} walks up with a chance to end it"
    if ctx.score_margin == 0 and ctx.inning >= 7:
        return f"{batter} steps in with the game on the line"
    if ctx.bases_loaded:
        return f"{batter} steps in with the bases loaded"
    if ctx.score_margin <= 1 and ctx.runners_on >= 1 and ctx.inning >= 7:
        return f"{batter} comes up with the tying run in play"
    if ctx.score_margin <= 2 and ctx.runners_on >= 1:
        return f"{batter} steps to the plate looking to flip the script"
    if ctx.score_margin >= 3:
        return f"{batter} looking to extend the lead"
    return f"{batter} digs in"


def _pitcher_headline(ctx: _ArcadeNarrativeContext) -> str:
    pitcher = ctx.pitcher_last
    if ctx.bases_loaded and ctx.outs >= 2:
        return "Bases loaded, two outs, no room left"
    if ctx.bases_loaded:
        return f"Bases loaded — {pitcher} needs an escape"
    if ctx.score_margin == 1 and ctx.runners_on >= 1:
        return f"{pitcher} protecting a one-run lead"
    if ctx.score_margin == 0 and ctx.runners_on >= 1:
        return f"{pitcher} working around traffic in a tie game"
    if ctx.runners_on >= 2:
        return f"{pitcher} trying to escape the jam"
    if ctx.outs >= 2 and ctx.runners_on >= 1:
        return f"{pitcher} one out from leaving runners stranded"
    return f"{pitcher} takes the mound under pressure"


def _headline(ctx: _ArcadeNarrativeContext) -> str:
    if ctx.moment_type == "pitcher":
        return _pitcher_headline(ctx)
    return _hitter_headline(ctx)


# ---------------------------------------------------------------------------
# Summary, why-this-moment, after-reveal
# ---------------------------------------------------------------------------


def _summary(ctx: _ArcadeNarrativeContext) -> str:
    half = _half_phrase(ctx.half, ctx.inning)
    outs = _outs_phrase(ctx.outs)
    runners = _runners_phrase(ctx.runners_on, ctx.bases_loaded)
    margin = _margin_phrase(ctx.score_margin, ctx.moment_type)
    if ctx.moment_type == "pitcher":
        return f"{half}, {outs}, {runners}, {ctx.pitcher_last} on the mound {margin}."
    return f"{half}, {outs}, {runners}, {ctx.batter_last} at the plate {margin}."


def _why_this_moment(ctx: _ArcadeNarrativeContext) -> str:
    tier = ctx.pressure_tier
    diff = ctx.difficulty
    if ctx.is_lead_change:
        stake = "the lead is on the line"
    elif ctx.is_tying:
        stake = "the tying run is in play"
    elif ctx.bases_loaded:
        stake = "the bases are loaded"
    elif ctx.score_margin <= 1 and ctx.inning >= 7:
        stake = "late innings, one swing decides it"
    elif ctx.runners_on >= 2:
        stake = "traffic on the bases raises the stakes"
    else:
        stake = "the pressure tier is set by the leverage of the spot"
    return f"Picked for the pack at {tier} pressure (difficulty {diff}) — {stake}."


def _hitter_after_reveal(ctx: _ArcadeNarrativeContext) -> str:
    batter = ctx.batter_last
    runs = ctx.runs_scored
    label = ctx.result_label.lower() if ctx.result_label else "play"
    if ctx.is_lead_change and runs >= 1:
        return f"{batter} flips the game with a {label} — {runs} run{'s' if runs != 1 else ''} home."
    if ctx.is_tying and runs >= 1:
        return f"{batter} ties it up with a {label}."
    if runs >= 2:
        return f"{batter} clears the bag with a {label} — {runs} runs come around."
    if runs == 1:
        return f"{batter} delivers with a {label} and a run scores."
    if ctx.event_type in {"strikeout", "field_out", "double_play", "triple_play"}:
        return f"{batter} is retired ({label}) — the threat passes."
    return f"{batter} stays alive with a {label}."


def _pitcher_after_reveal(ctx: _ArcadeNarrativeContext) -> str:
    pitcher = ctx.pitcher_last
    runs = ctx.runs_scored
    label = ctx.result_label.lower() if ctx.result_label else "play"
    if ctx.event_type == "strikeout" and runs == 0:
        return f"{pitcher} punches him out — escape made."
    if ctx.event_type in {"double_play", "triple_play"} and runs == 0:
        return f"{pitcher} gets out of it on a {label}."
    if ctx.event_type in {"field_out", "fielders_choice"} and runs == 0:
        return f"{pitcher} induces a {label} — pressure released."
    if ctx.event_type in {"walk", "hit_by_pitch"} and ctx.bases_loaded:
        return f"{pitcher} gives up a {label} — a run is forced in."
    if ctx.is_lead_change and runs >= 1:
        return f"{pitcher} surrenders the lead on a {label} — {runs} run{'s' if runs != 1 else ''} score."
    if runs >= 2:
        return f"{pitcher} is touched up for {runs} on a {label}."
    if runs == 1:
        return f"{pitcher} gives up a {label} — a run crosses."
    return f"{pitcher} settles for a {label} — damage limited."


def _after_reveal(ctx: _ArcadeNarrativeContext) -> str:
    if ctx.moment_type == "pitcher":
        return _pitcher_after_reveal(ctx)
    return _hitter_after_reveal(ctx)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_arcade_narrative(
    ctx: _ArcadeNarrativeContext,
) -> ArcadeNarrativeOutput:
    """Render the four arcade narrative fields from a prepared context.

    Pure function — same context always produces the same output.
    """
    return ArcadeNarrativeOutput(
        headline=_headline(ctx),
        summary=_summary(ctx),
        why_this_moment=_why_this_moment(ctx),
        after_reveal=_after_reveal(ctx),
    )


__all__ = [
    "ArcadeNarrativeOutput",
    "MomentType",
    "_ArcadeNarrativeContext",
    "generate_arcade_narrative",
]
