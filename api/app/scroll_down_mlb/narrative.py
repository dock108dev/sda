"""Narrative sentence rewrite.

Port of `scroll-down-web/web/src/lib/narrative.ts`.

Strict rule preserved: every clause must be supported by data on the card.
No invented stadium reactions, pitch types, or unattributed commentary.
Returns None to signal "fall back to humanized upstream description."
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from .internal_types import BuiltPlayCard

_SUFFIX_PATTERN = re.compile(r"^(Jr\.?|Sr\.?|II|III|IV)$", re.IGNORECASE)


def _last_name_only(full: str | None) -> str | None:
    if not full:
        return None
    trimmed = full.strip()
    if not trimmed:
        return None
    parts = trimmed.split()
    last = parts[-1]
    if _SUFFIX_PATTERN.match(last) and len(parts) >= 2:
        last = parts[-2]
    return last.rstrip(".,;")


def _occupied(state: dict[str, bool]) -> int:
    return (
        (1 if state.get("first") else 0)
        + (1 if state.get("second") else 0)
        + (1 if state.get("third") else 0)
    )


@dataclass(frozen=True)
class _NarrativeContext:
    is_late: bool
    is_close_game: bool
    runs_scored: int
    runners_on_before: int
    bases_loaded_before: bool
    bases_loaded_after: bool
    two_outs_before: bool
    inning_over: bool
    batter_last: str | None
    pitcher_last: str | None


def _build_context(card: BuiltPlayCard) -> _NarrativeContext:
    before = card.base_state_before
    after = card.base_state_after
    runs_scored = (
        (card.score_after_home - card.score_before_home)
        + (card.score_after_away - card.score_before_away)
    )
    return _NarrativeContext(
        is_late=card.inning >= 7,
        is_close_game=abs(card.score_before_home - card.score_before_away) <= 2,
        runs_scored=max(0, runs_scored),
        runners_on_before=_occupied(before),
        bases_loaded_before=bool(
            before.get("first") and before.get("second") and before.get("third")
        ),
        bases_loaded_after=bool(
            after.get("first") and after.get("second") and after.get("third")
        ),
        two_outs_before=card.outs_before >= 2,
        inning_over=card.outs_after >= 3,
        batter_last=_last_name_only(card.batter_name),
        pitcher_last=_last_name_only(card.pitcher_name),
    )


def _end_punct(s: str) -> str:
    if not s:
        return s
    return s if s.endswith((".", "!", "?")) else f"{s}."


def _capitalize(s: str) -> str:
    if not s:
        return s
    return s[0].upper() + s[1:]


# ---------------------------------------------------------------------------
# Per-event narrators
# ---------------------------------------------------------------------------


def _narrate_walk(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.bases_loaded_after and ctx.bases_loaded_before:
        return f"{who} walks home a run with the bases loaded."
    if ctx.bases_loaded_after:
        return f"{who} draws a walk to load the bases."
    if ctx.runners_on_before >= 1 and ctx.is_late:
        return f"{who} works a walk to add a runner late."
    if ctx.runners_on_before >= 1:
        return f"{who} draws a walk and another runner is aboard."
    return f"{who} works the count and draws a walk."


def _narrate_hbp(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.bases_loaded_after:
        return f"{who} gets clipped by a pitch and a run is forced in."
    if ctx.runners_on_before >= 2:
        return f"{who} is hit by a pitch — the bases get more crowded."
    if ctx.runners_on_before == 1:
        return f"{who} is hit by a pitch to put a second runner on."
    return f"{who} is hit by a pitch to reach."


def _narrate_strikeout(ctx: _NarrativeContext) -> str:
    pitcher = ctx.pitcher_last
    batter = ctx.batter_last or "the batter"
    if ctx.inning_over and ctx.runners_on_before > 0:
        return (
            f"{pitcher} punches out {batter} to strand the threat."
            if pitcher
            else f"{_capitalize(batter)} strikes out and the threat is stranded."
        )
    if ctx.inning_over:
        return (
            f"{pitcher} punches out {batter} to end the half."
            if pitcher
            else f"{_capitalize(batter)} strikes out to end the half."
        )
    if ctx.two_outs_before and ctx.runners_on_before > 0:
        return (
            f"{pitcher} freezes {batter} for the strikeout — runners stranded."
            if pitcher
            else f"{_capitalize(batter)} strikes out — runners stranded."
        )
    return (
        f"{pitcher} strikes out {batter}."
        if pitcher
        else f"{_capitalize(batter)} strikes out."
    )


def _narrate_single(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 2:
        return f"{who} singles and {ctx.runs_scored} runs come home."
    if ctx.runs_scored == 1:
        return f"{who} singles home a run."
    if ctx.bases_loaded_after:
        return f"{who} singles to load the bases."
    if ctx.runners_on_before >= 1:
        return f"{who} singles and pushes the runner along."
    return f"{who} lines a single into play."


def _narrate_double(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 2:
        return f"{who} doubles into the gap and {ctx.runs_scored} score."
    if ctx.runs_scored == 1:
        return f"{who} doubles in a run."
    if ctx.runners_on_before >= 1:
        return f"{who} doubles to put runners in scoring position."
    return f"{who} laces a double."


def _narrate_triple(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 1:
        tail = "a run scores" if ctx.runs_scored == 1 else f"{ctx.runs_scored} runs score"
        return f"{who} legs out a triple and {tail}."
    return f"{who} legs out a triple."


def _narrate_home_run(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 4:
        return f"{who} crushes a grand slam."
    if ctx.runs_scored == 3:
        return f"{who} launches a 3-run homer."
    if ctx.runs_scored == 2:
        return f"{who} hits a 2-run shot."
    return f"{who} goes deep for a solo home run."


def _narrate_field_out(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.inning_over and ctx.runners_on_before > 0:
        return f"{who} is retired to end the half — runners left on."
    if ctx.inning_over:
        return f"{who} is retired to end the half."
    if ctx.runs_scored >= 1:
        return f"{who} gets retired but a run crosses on the play."
    return f"{who} is retired."


def _narrate_double_play(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.inning_over:
        return f"{who} grounds into a double play to end the threat."
    return f"{who} grounds into a double play — two outs in a hurry."


def _narrate_triple_play(_: _NarrativeContext) -> str:
    return "Triple play — the half is over in a single swing."


def _narrate_sacrifice(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 1:
        tail = "a run scores" if ctx.runs_scored == 1 else f"{ctx.runs_scored} runs score"
        return f"{who} lifts a sacrifice and {tail}."
    return f"{who} moves the runner over with a sacrifice."


def _narrate_error(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 1:
        return f"{who} reaches on an error and a run scores."
    return f"{who} reaches on an error."


def _narrate_fielders_choice(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    if ctx.runs_scored >= 1:
        return f"{who} reaches on a fielder's choice and a run comes in."
    return f"{who} reaches on a fielder's choice; the lead runner is retired."


def _narrate_stolen_base(ctx: _NarrativeContext) -> str:
    return (
        f"Steal — a runner moves up behind {ctx.batter_last}."
        if ctx.batter_last
        else "A runner steals the next bag."
    )


def _narrate_caught_stealing(_: _NarrativeContext) -> str:
    return "Runner caught stealing — the threat is over."


def _narrate_pickoff(_: _NarrativeContext) -> str:
    return "Pickoff — the runner is caught off the bag."


def _narrate_wild_pitch(ctx: _NarrativeContext) -> str:
    if ctx.runs_scored >= 1:
        return "Wild pitch — a run scores on the loose ball."
    return "Wild pitch — every runner moves up."


def _narrate_passed_ball(ctx: _NarrativeContext) -> str:
    if ctx.runs_scored >= 1:
        return "Passed ball at the plate — a run scores."
    return "Passed ball — runners advance."


def _narrate_balk(_: _NarrativeContext) -> str:
    return "Balk called — every runner moves up a base."


def _narrate_catcher_interference(ctx: _NarrativeContext) -> str:
    who = ctx.batter_last or "The batter"
    return f"Catcher's interference — {who} is awarded first."


_NARRATORS: dict[str, Callable[[_NarrativeContext], str]] = {
    "walk": _narrate_walk,
    "hit_by_pitch": _narrate_hbp,
    "strikeout": _narrate_strikeout,
    "single": _narrate_single,
    "double": _narrate_double,
    "triple": _narrate_triple,
    "home_run": _narrate_home_run,
    "field_out": _narrate_field_out,
    "double_play": _narrate_double_play,
    "triple_play": _narrate_triple_play,
    "sacrifice": _narrate_sacrifice,
    "error": _narrate_error,
    "fielders_choice": _narrate_fielders_choice,
    "stolen_base": _narrate_stolen_base,
    "caught_stealing": _narrate_caught_stealing,
    "pickoff": _narrate_pickoff,
    "wild_pitch": _narrate_wild_pitch,
    "passed_ball": _narrate_passed_ball,
    "balk": _narrate_balk,
    "catcher_interference": _narrate_catcher_interference,
}


def narrative_for_card(card: BuiltPlayCard) -> str | None:
    """Return a rewritten narrative sentence, or None to fall back to the
    humanized upstream description."""
    event = card.event_type
    if not event:
        return None
    fn = _NARRATORS.get(event)
    if not fn:
        return None
    sentence = fn(_build_context(card))
    if not sentence:
        return None
    return _end_punct(sentence)


__all__ = ["narrative_for_card"]
