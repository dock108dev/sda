"""Per-event reveal-type classification + result-flag construction.

Two pure helpers consumed by the half-inning container builder:

* :func:`classify_reveal_type` maps an event_type string to one of three
  reveal animation profiles ('pitch' | 'plate_appearance' | 'play').
* :func:`build_event_result` assembles a :class:`ScrollDownEventResult`
  from event_type, description, and the deterministic before/after
  snapshots computed in `compute_timeline`.

Kept out of ``game_state.py`` because the classification is independent
of timeline reconstruction — it operates on already-classified event
types and shouldn't grow with the state walk.
"""

from __future__ import annotations

from typing import Literal

from .result_labels import _primary_for
from .schemas import ScrollDownEventResult
from .visual_mapper import outs_delta_for

__all__ = ["classify_reveal_type", "build_event_result"]


RevealType = Literal["pitch", "plate_appearance", "play"]


_PITCH_LEVEL_EVENTS: frozenset[str] = frozenset(
    {
        "ball",
        "called_strike",
        "swinging_strike",
        "foul",
        "balk",
        "wild_pitch",
        "passed_ball",
    }
)

# PA-terminal at-bat results: each ends the batter's plate appearance with
# a single named outcome (a hit, a walk, a single batter-only out, etc.).
# Multi-runner plays (double_play, sacrifice with runner advance) and pure
# fielding/runner plays (stolen_base, caught_stealing, pickoff) fall to
# 'play' instead.
_PA_TERMINAL_EVENTS: frozenset[str] = frozenset(
    {
        "strikeout",
        "walk",
        "hit_by_pitch",
        "catcher_interference",
        "single",
        "double",
        "triple",
        "home_run",
        "error",
        "field_out",
    }
)


def classify_reveal_type(event_type: str | None) -> RevealType:
    """Map an event_type to its reveal animation family.

    Returns ``'pitch'`` for pitch-level events, ``'plate_appearance'`` for
    PA-terminal at-bat results, and ``'play'`` for everything else
    (multi-runner plays, fielding/runner-only events, unknown).
    """
    if not event_type:
        return "play"
    if event_type in _PITCH_LEVEL_EVENTS:
        return "pitch"
    if event_type in _PA_TERMINAL_EVENTS:
        return "plate_appearance"
    return "play"


_HIT_EVENTS: frozenset[str] = frozenset({"single", "double", "triple", "home_run"})


def build_event_result(
    *,
    event_type: str | None,
    description: str,
    outs_after: int,
    score_change_home: int,
    score_change_away: int,
) -> ScrollDownEventResult:
    """Assemble the canonical result payload for a single event.

    Flags are derived deterministically:

      * ``is_out`` mirrors :func:`outs_delta_for` — true whenever the
        event produced at least one out (covers strikeouts, force/fly/tag
        outs, double/triple plays, sacrifices, fielders' choice, caught
        stealing, pickoffs).
      * ``is_scoring_play`` is true when the per-team delta sums positive.
      * ``is_inning_ending`` is true when post-play outs reach 3.

    ``label`` reuses the chip primary (``_primary_for``) so the renderer
    can show the same canonical string the deck card uses without
    re-deriving it.
    """
    delta = max(0, (score_change_home or 0) + (score_change_away or 0))
    label = _primary_for(event_type, description)
    is_out = bool(event_type) and outs_delta_for(event_type or "") > 0
    return ScrollDownEventResult(
        label=label,
        description=description,
        event_type=event_type,
        is_out=is_out,
        is_strikeout=event_type == "strikeout",
        is_walk=event_type == "walk",
        is_hit=event_type in _HIT_EVENTS,
        is_scoring_play=delta > 0,
        is_inning_ending=outs_after >= 3,
    )
