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
from typing import Any, Optional

from .internal_types import RunnerAdvance


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
    ("double", re.compile(r"\bdoubles?\b(?!\s*play)", re.IGNORECASE)),
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
        re.compile(
            r"\b(strikes?\s*out|struck\s*out|strikeouts?|punches?\s*out|called\s*out\s*on\s*strikes|k\b)",
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


# ---------------------------------------------------------------------------
# Direction / fielder regexes for ball-path zone selection
# ---------------------------------------------------------------------------

_DIR_LEFT_CENTER = re.compile(
    r"\bleft[-\s]+center(?:\s*field(?:er)?)?\b", re.IGNORECASE
)
_DIR_RIGHT_CENTER = re.compile(
    r"\bright[-\s]+center(?:\s*field(?:er)?)?\b", re.IGNORECASE
)
_DIR_LEFT = re.compile(
    r"\b(left\s*field(?:er)?|to\s*left|\blf\b|down\s*the\s*(?:left[-\s])?line)\b",
    re.IGNORECASE,
)
_DIR_RIGHT = re.compile(
    r"\b(right\s*field(?:er)?|to\s*right|\brf\b|down\s*the\s*right[-\s]line)\b",
    re.IGNORECASE,
)
_DIR_CENTER = re.compile(
    r"\b(center\s*field(?:er)?|to\s*center|\bcf\b|up\s*the\s*middle)\b",
    re.IGNORECASE,
)
_FIELDER_3B = re.compile(r"\bthird\s*base(?:man)?\b|\b3b\b", re.IGNORECASE)
_FIELDER_SS = re.compile(r"\bshort(?:stop)?\b|\bss\b", re.IGNORECASE)
_FIELDER_2B = re.compile(r"\bsecond\s*base(?:man)?\b|\b2b\b", re.IGNORECASE)
_FIELDER_1B = re.compile(r"\bfirst\s*base(?:man)?\b|\b1b\b", re.IGNORECASE)
_FIELDER_P = re.compile(r"\bpitcher\b", re.IGNORECASE)

_DESC_GROUNDER = re.compile(r"\bground(?:s|ed|er|ing)?\b", re.IGNORECASE)
_DESC_LINE = re.compile(r"\blin(?:es?|ed|ing|er|e\s*drive)\b", re.IGNORECASE)
_DESC_FLY = re.compile(r"\bfl(?:y|ies|ied|ying)\b", re.IGNORECASE)
_DESC_POPUP = re.compile(r"\bpop(?:s|ped|up|ping)?\b", re.IGNORECASE)
_DESC_FOUL = re.compile(r"\bfoul", re.IGNORECASE)


def _outfield_zone(description: str, fallback: str) -> str:
    if _DIR_LEFT_CENTER.search(description):
        return "fly_lcf"
    if _DIR_RIGHT_CENTER.search(description):
        return "fly_rcf"
    if _DIR_LEFT.search(description):
        return "fly_lf"
    if _DIR_RIGHT.search(description):
        return "fly_rf"
    if _DIR_CENTER.search(description):
        return "fly_cf"
    return fallback


def _ground_zone(description: str) -> str:
    """First fielder mentioned wins (the throw destination doesn't count)."""
    matches: list[tuple[int, str]] = []
    for pattern, zone in (
        (_FIELDER_3B, "ground_3b"),
        (_FIELDER_SS, "ground_ss"),
        (_FIELDER_2B, "ground_2b"),
        (_FIELDER_1B, "ground_1b"),
        (_FIELDER_P, "ground_p"),
    ):
        m = pattern.search(description)
        if m is not None:
            matches.append((m.start(), zone))
    if matches:
        matches.sort(key=lambda x: x[0])
        return matches[0][1]
    if _DIR_LEFT.search(description):
        return "ground_ss"
    if _DIR_RIGHT.search(description):
        return "ground_2b"
    return "ground_p"


def _line_zone(description: str) -> str:
    if _DIR_LEFT.search(description):
        return "line_left"
    if _DIR_RIGHT.search(description):
        return "line_right"
    if _DIR_CENTER.search(description):
        return "line_center"
    if _FIELDER_3B.search(description) or _FIELDER_SS.search(description):
        return "line_left"
    if _FIELDER_2B.search(description) or _FIELDER_1B.search(description):
        return "line_right"
    return "line_center"


def _home_run_zone(description: str) -> str:
    if _DIR_LEFT_CENTER.search(description) or _DIR_LEFT.search(description):
        return "home_run_left"
    if _DIR_RIGHT_CENTER.search(description) or _DIR_RIGHT.search(description):
        return "home_run_right"
    return "home_run_center"


def ball_path_from_event(event: str, description: str) -> str:
    """Return the BallPath label for a play. Frontend SVG renderer maps
    the label to a path d-string."""
    if event == "home_run":
        return _home_run_zone(description)
    if event in ("strikeout", "walk", "hit_by_pitch"):
        return "none"
    if event in ("stolen_base", "caught_stealing", "pickoff", "balk", "catcher_interference"):
        return "none"
    if event in ("wild_pitch", "passed_ball"):
        return "pitch"
    if event in ("triple", "double"):
        if _DESC_LINE.search(description):
            return _line_zone(description)
        return _outfield_zone(description, "fly_cf" if event == "triple" else "fly_lf")
    if event == "single":
        if (
            _DIR_LEFT_CENTER.search(description)
            or _DIR_RIGHT_CENTER.search(description)
            or _DIR_LEFT.search(description)
            or _DIR_RIGHT.search(description)
            or _DIR_CENTER.search(description)
        ):
            return _outfield_zone(description, "fly_cf")
        if _DESC_LINE.search(description):
            return _line_zone(description)
        if _DESC_GROUNDER.search(description):
            return _ground_zone(description)
        return "fly_cf"
    if event in (
        "double_play",
        "triple_play",
        "field_out",
        "sacrifice",
        "fielders_choice",
        "error",
        "other",
    ):
        if _DESC_FOUL.search(description):
            return "foul"
        if _DESC_LINE.search(description):
            return _line_zone(description)
        if _DESC_FLY.search(description):
            return _outfield_zone(description, "fly_cf")
        if _DESC_POPUP.search(description):
            return "popup"
        if _DESC_GROUNDER.search(description):
            return _ground_zone(description)
        if (
            _FIELDER_3B.search(description)
            or _FIELDER_SS.search(description)
            or _FIELDER_2B.search(description)
            or _FIELDER_1B.search(description)
            or _FIELDER_P.search(description)
        ):
            return _ground_zone(description)
        if (
            _DIR_LEFT.search(description)
            or _DIR_RIGHT.search(description)
            or _DIR_CENTER.search(description)
        ):
            return _line_zone(description)
        return "none" if event == "other" else "ground_p"
    return "none"


# ---------------------------------------------------------------------------
# Animation profile (port of classifyAnimationProfile)
# ---------------------------------------------------------------------------


def classify_animation_profile(event: str, description: str) -> str:
    if event in ("caught_stealing", "field_out") and re.search(
        r"\brundown\b", description, re.IGNORECASE
    ):
        return "rundown"
    if event == "home_run":
        return "home_run"
    if event in ("walk", "hit_by_pitch", "catcher_interference"):
        return "walk"
    if event == "strikeout":
        return "strikeout"
    if event in ("stolen_base", "caught_stealing", "pickoff", "balk"):
        return "stolen_base"
    if event in ("wild_pitch", "passed_ball"):
        return "wild_pitch"
    if event in ("double_play", "triple_play"):
        return (
            "double_play_fly"
            if (_DESC_FLY.search(description) or _DESC_POPUP.search(description))
            else "double_play_grounder"
        )
    if event == "sacrifice":
        return "sacrifice_fly" if _DESC_FLY.search(description) else "routine_grounder"
    if event == "field_out":
        if _DESC_POPUP.search(description):
            return "popup"
        if _DESC_FLY.search(description):
            if re.search(
                r"\bdeep|warning track|wall|caught at the wall", description, re.IGNORECASE
            ):
                return "deep_fly"
            return "shallow_fly"
        if _DESC_LINE.search(description):
            return "line_drive"
        return "routine_grounder"
    if event == "fielders_choice":
        return "hard_grounder"
    if event == "single":
        if _DESC_GROUNDER.search(description):
            return "hard_grounder"
        if _DESC_LINE.search(description):
            return "line_drive"
        return "shallow_fly"
    if event in ("double", "triple"):
        if _DESC_LINE.search(description):
            return "line_drive"
        return "deep_fly"
    return "other"


def visual_intensity(event: str) -> str:
    if event in ("home_run", "triple_play", "double_play", "triple"):
        return "high"
    if event in (
        "double",
        "single",
        "error",
        "fielders_choice",
        "wild_pitch",
        "passed_ball",
        "caught_stealing",
        "pickoff",
    ):
        return "medium"
    return "low"


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


def batter_dest_for_event(event: str) -> Optional[str]:
    return _BATTER_DEST_BY_EVENT.get(event)


# ---------------------------------------------------------------------------
# Runner movement style (port of classifyRunnerStyle)
# ---------------------------------------------------------------------------


def classify_runner_style(adv: RunnerAdvance, event_type: Optional[str]) -> str:
    if adv.to == "out":
        if not adv.out_at:
            return "in_place_out"
        if event_type in ("double_play", "triple_play"):
            return "double_play"
        if event_type in ("fielders_choice", "caught_stealing", "pickoff"):
            return "forced_out"
        return "tagged_out"
    if adv.to == "home":
        return "score"
    if event_type in ("stolen_base", "wild_pitch", "passed_ball", "balk"):
        return "steal"
    if event_type in ("walk", "hit_by_pitch", "catcher_interference"):
        return "walk_shuffle"
    if event_type in ("double_play", "triple_play"):
        return "double_play"
    return "advance"


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
    "classify_runner_style",
    "compute_leverage_tier",
    "downgrade_implausible",
    "outs_delta_for",
    "visual_intensity",
]
