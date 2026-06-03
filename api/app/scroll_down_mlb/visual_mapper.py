"""Event classification + visual payload mapping.

Ports from `scroll-down-web/web/src/lib/`:

  * `catchup-cards.ts`  : classifyEvent, ballPathFromEvent,
                          classifyAnimationProfile, visualIntensity,
                          outsDeltaFor, downgradeImplausible,
                          batterDestForEvent
  * `runner-paths.ts`   : classifyRunnerStyle (computation half only)
  * `leverage.ts`       : computeLeverage (the 0/1/2 tier output)

These functions are spoiler-safe: they take raw play data and reconstructed
state and return classification labels. SVG geometry stays on the frontend.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Event classification (port of classifyEvent)
# ---------------------------------------------------------------------------

# Order matters: most-specific first. Triple play before triple, etc.
_EVENT_KEYWORDS: list[tuple[str, re.Pattern]] = [
    ("triple_play", re.compile(r"\btriple[-\s]?play\b", re.IGNORECASE)),
    ("double_play", re.compile(r"\bdouble[-\s]?play|\bgidp\b", re.IGNORECASE)),
    (
        "home_run",
        re.compile(r"\b(home\s*run|homers?|grand\s*slam|hr)\b", re.IGNORECASE),
    ),
    ("triple", re.compile(r"\btriples?\b", re.IGNORECASE)),
    # Negative lookahead excludes lineup/roster phrases like "double play",
    # "double switch" (NL pitcher swap), "double header" (two games in a day).
    ("double", re.compile(r"\bdoubles?\b(?![-\s]+(?:play|switch|header)\b)", re.IGNORECASE)),
    ("single", re.compile(r"\bsingles?\b", re.IGNORECASE)),
    ("hit_by_pitch", re.compile(r"\b(hit\s*by\s*pitch|hbp)\b", re.IGNORECASE)),
    (
        "walk",
        re.compile(
            r"\b(walks?|base\s*on\s*balls|bb|intentional\s*walk|ibb)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "catcher_interference",
        re.compile(r"\bcatcher(?:'s)?\s*interference\b", re.IGNORECASE),
    ),
    (
        "strikeout",
        # The bare `\bk\b` shorthand was removed because it false-matched on
        # player-name initials like "K. Martinez". Upstream `playType="K"`
        # is still honored by classify_event's explicit fast-path.
        re.compile(
            r"\b(strikes?\s*out|struck\s*out|strikeouts?|punches?\s*out|called\s*out\s*on\s*strikes)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "caught_stealing",
        re.compile(r"\bcaught\s*stealing|throw(?:n)?\s*out\s*stealing|cs\b", re.IGNORECASE),
    ),
    ("pickoff", re.compile(r"\bpicked\s*off|pickoff\b", re.IGNORECASE)),
    ("stolen_base", re.compile(r"\bsteals?\b|\bstolen\s*base", re.IGNORECASE)),
    ("balk", re.compile(r"\bbalk\b", re.IGNORECASE)),
    ("passed_ball", re.compile(r"\bpassed\s*ball\b", re.IGNORECASE)),
    ("wild_pitch", re.compile(r"\bwild\s*pitch\b", re.IGNORECASE)),
    ("sacrifice", re.compile(r"\bsacrifice|sac\s*(fly|bunt)\b", re.IGNORECASE)),
    (
        "fielders_choice",
        re.compile(r"\bfielder['']?s\s*choice|\bfc\b", re.IGNORECASE),
    ),
    ("error", re.compile(r"\b(reaches\s*on.*error|error\b)", re.IGNORECASE)),
    (
        "field_out",
        re.compile(
            r"\b(grounds?\s*out|flies\s*out|fly\s*out|pops?\s*out|lines?\s*out|line\s*out|forces?\s*out|force\s*out|tags?\s*out|tag\s*out|ground\s*out|out\b)",
            re.IGNORECASE,
        ),
    ),
]

_KNOWN_EVENT_TYPES = frozenset(
    {
        "single",
        "double",
        "triple",
        "home_run",
        "walk",
        "hit_by_pitch",
        "strikeout",
        "field_out",
        "double_play",
        "triple_play",
        "fielders_choice",
        "error",
        "stolen_base",
        "caught_stealing",
        "pickoff",
        "wild_pitch",
        "passed_ball",
        "balk",
        "sacrifice",
        "catcher_interference",
    }
)


def classify_event(play: dict[str, Any]) -> str:
    """Classify a raw upstream play to a normalized event type."""
    explicit = (play.get("playType") or "").strip().lower()
    explicit = re.sub(r"[\s-]+", "_", explicit)
    if explicit:
        if explicit in _KNOWN_EVENT_TYPES:
            return explicit
        if "triple_play" in explicit:
            return "triple_play"
        if "home_run" in explicit:
            return "home_run"
        if "double_play" in explicit or explicit == "gidp":
            return "double_play"
        if "triple" in explicit:
            return "triple"
        if "double" in explicit:
            return "double"
        if "single" in explicit:
            return "single"
        if "hit_by_pitch" in explicit or explicit == "hbp":
            return "hit_by_pitch"
        if "intentional_walk" in explicit or explicit == "ibb":
            return "walk"
        if "walk" in explicit or explicit == "bb":
            return "walk"
        if "strikeout" in explicit or explicit in ("k", "ko"):
            return "strikeout"
        if "caught_stealing" in explicit or explicit == "cs":
            return "caught_stealing"
        if "pickoff" in explicit:
            return "pickoff"
        if "steal" in explicit or "stolen" in explicit:
            return "stolen_base"
        if "balk" in explicit:
            return "balk"
        if "passed_ball" in explicit:
            return "passed_ball"
        if "wild_pitch" in explicit or "wild" in explicit:
            return "wild_pitch"
        if "catcher_interference" in explicit:
            return "catcher_interference"
        if "fielders_choice" in explicit or explicit == "fc":
            return "fielders_choice"
        if "error" in explicit:
            return "error"
        if "sac" in explicit:
            return "sacrifice"
        if "out" in explicit:
            return "field_out"
    description = play.get("description") or ""
    for event_type, pattern in _EVENT_KEYWORDS:
        if pattern.search(description):
            return event_type
    return "other"

from .visual_paths import (
    ball_path_from_event,
    classify_animation_profile,
    display_hint_fields,
)


# ---------------------------------------------------------------------------
# Outs delta + plausibility downgrade + batter destination
# ---------------------------------------------------------------------------


def outs_delta_for(event: str) -> int:
    if event == "triple_play":
        return 3
    if event == "double_play":
        return 2
    if event in (
        "strikeout",
        "field_out",
        "sacrifice",
        "fielders_choice",
        "caught_stealing",
        "pickoff",
    ):
        return 1
    return 0


def downgrade_implausible(before: dict[str, bool], event: str) -> str:
    """Plausibility downgrade: if upstream says triple_play but the bases
    can't physically support one, step it down."""
    occupied = (
        (1 if before.get("first") else 0)
        + (1 if before.get("second") else 0)
        + (1 if before.get("third") else 0)
    )
    if event == "triple_play" and occupied < 2:
        return "double_play" if occupied >= 1 else "field_out"
    if event == "double_play" and occupied < 1:
        return "field_out"
    return event


_BATTER_DEST_BY_EVENT: dict[str, str] = {
    "single": "first",
    "double": "second",
    "triple": "third",
    "home_run": "home",
    "walk": "first",
    "hit_by_pitch": "first",
    "catcher_interference": "first",
    "error": "first",
    "fielders_choice": "first",
    "field_out": "out",
    "double_play": "out",
    "triple_play": "out",
    "strikeout": "out",
    "sacrifice": "out",
}


def batter_dest_for_event(event: str) -> str | None:
    return _BATTER_DEST_BY_EVENT.get(event)


# ---------------------------------------------------------------------------
# Leverage tier (port of computeLeverage from leverage.ts)
# ---------------------------------------------------------------------------


def compute_leverage_tier(
    *,
    inning: int,
    score_before_home: int,
    score_before_away: int,
    score_after_home: int,
    score_after_away: int,
    outs_before: int,
    bases_loaded_before: bool,
) -> int:
    """Pure tier classifier from a play's reconstructed state. Returns
    0 (routine), 1 (elevated), or 2 (climactic)."""
    is_late = inning >= 7
    is_close = abs(score_before_home - score_before_away) <= 2
    is_tied = score_before_home == score_before_away
    two_outs_before = outs_before == 2
    runs_scored = (
        score_after_home + score_after_away
        - (score_before_home + score_before_away)
    )
    big_score = runs_scored >= 2

    def lead(home: int, away: int) -> str:
        if home > away:
            return "home"
        if home < away:
            return "away"
        return "tied"

    before_lead = lead(score_before_home, score_before_away)
    after_lead = lead(score_after_home, score_after_away)
    leads_changed = (
        before_lead != "tied"
        and after_lead != "tied"
        and before_lead != after_lead
    )

    score = (
        (1 if is_late else 0)
        + (1 if is_close else 0)
        + (1 if is_tied else 0)
        + (1 if two_outs_before else 0)
        + (1 if bases_loaded_before else 0)
        + (1 if big_score else 0)
        + (2 if leads_changed else 0)
    )
    if score <= 1:
        return 0
    if score <= 3:
        return 1
    return 2


__all__ = [
    "ball_path_from_event",
    "batter_dest_for_event",
    "classify_animation_profile",
    "classify_event",
    "compute_leverage_tier",
    "display_hint_fields",
    "downgrade_implausible",
    "outs_delta_for",
    "visual_intensity",
]
