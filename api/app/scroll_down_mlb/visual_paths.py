"""MLB visual path, animation, and display-hint mapping."""

from __future__ import annotations

import re

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


_RELAY_THROW = re.compile(
    r"\b(?:throw(?:s|n|ing)?|relay(?:s|ed|ing)?(?:\s+throw)?)\s+to\s+\S+",
    re.IGNORECASE,
)


def _ground_zone(description: str) -> str:
    """First fielder mentioned wins (the throw destination doesn't count).

    Relay-throw clauses (e.g. "shortstop throws to first") are stripped
    before the fielder scan so the throw *destination* doesn't get
    mis-tagged as the fielding position.
    """
    cleaned = _RELAY_THROW.sub(" ", description)
    matches: list[tuple[int, str]] = []
    for pattern, zone in (
        (_FIELDER_3B, "ground_3b"),
        (_FIELDER_SS, "ground_ss"),
        (_FIELDER_2B, "ground_2b"),
        (_FIELDER_1B, "ground_1b"),
        (_FIELDER_P, "ground_p"),
    ):
        m = pattern.search(cleaned)
        if m is not None:
            matches.append((m.start(), zone))
    if matches:
        matches.sort(key=lambda x: x[0])
        return matches[0][1]
    if _DIR_LEFT.search(cleaned):
        return "ground_ss"
    if _DIR_RIGHT.search(cleaned):
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


_DESC_WP_OR_PB = re.compile(r"\bwild\s*pitch\b|\bpassed\s*ball\b", re.IGNORECASE)
_DESC_CS_HOME = re.compile(
    r"\bcaught\s+stealing\s+home\b|\bstealing\s+home\b|\bat\s+home\b|\bto\s+home\b",
    re.IGNORECASE,
)
_DESC_THROWING_ERROR = re.compile(
    r"\bthrow(?:ing|s|n)?\b[^.]*\berror\b|\berror[^.]*\bthrow(?:ing|s|n)?\b",
    re.IGNORECASE,
)
_THROW_TARGET = re.compile(
    r"\bthrow(?:s|n|ing)?\s+(?:wildly\s+|the\s+ball\s+)?(?:to\s+)?(first|second|third|home)\b",
    re.IGNORECASE,
)


def ball_path_from_event(event: str, description: str) -> str:
    """Return the BallPath label for a play. Frontend SVG renderer maps
    the label to a path d-string."""
    if event == "home_run":
        return _home_run_zone(description)
    if event == "strikeout":
        # Dropped third strike / strikeout-with-WP/PB has a real pitch
        # trajectory (the ball got past the catcher). A swinging or
        # called K has no ball path at all.
        if _DESC_WP_OR_PB.search(description):
            return "pitch"
        return "none"
    if event in ("walk", "hit_by_pitch"):
        return "none"
    if event == "caught_stealing":
        # Caught stealing at home involves a real throw (catcher to home or
        # outfield to home). Surface a path so the renderer can show the
        # throw arc; the standard 2B/3B caught-stealing stays pathless.
        if _DESC_CS_HOME.search(description):
            return "ground_p"
        return "none"
    if event in ("stolen_base", "pickoff", "balk", "catcher_interference"):
        return "none"
    if event in ("wild_pitch", "passed_ball"):
        return "pitch"
    if event in ("triple", "double"):
        if _DESC_LINE.search(description):
            return _line_zone(description)
        return _outfield_zone(description, "fly_cf" if event == "triple" else "fly_lf")
    if event == "single":
        # Grounder check runs first: a description like "singles to left,
        # ground ball through the hole" must classify as a grounder, not as
        # a fly to left.
        if _DESC_GROUNDER.search(description):
            return _ground_zone(description)
        if _DESC_LINE.search(description):
            return _line_zone(description)
        if (
            _DIR_LEFT_CENTER.search(description)
            or _DIR_RIGHT_CENTER.search(description)
            or _DIR_LEFT.search(description)
            or _DIR_RIGHT.search(description)
            or _DIR_CENTER.search(description)
        ):
            return _outfield_zone(description, "fly_cf")
        return "fly_cf"
    if event == "error" and _DESC_THROWING_ERROR.search(description):
        # Throwing errors: the ball travels from the errant fielder to the
        # throw target. Tag the destination base so the overlay shows the
        # throw, not a phantom grounder back to the pitcher.
        target_match = _THROW_TARGET.search(description)
        if target_match:
            target = target_match.group(1).lower()
            return {
                "first": "ground_1b",
                "second": "ground_2b",
                "third": "ground_3b",
                "home": "ground_p",
            }[target]
        return "ground_p"
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
    # A pickoff that becomes a rundown is visually a rundown, not a
    # stolen-base attempt — the stolen-base profile was misleading
    # because the runner zig-zags rather than running straight.
    if event in ("caught_stealing", "field_out", "pickoff") and re.search(
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


_NON_BATTED_BALL_EVENTS = frozenset(
    {
        "strikeout",
        "walk",
        "hit_by_pitch",
        "stolen_base",
        "caught_stealing",
        "pickoff",
        "balk",
        "catcher_interference",
        "wild_pitch",
        "passed_ball",
    }
)


def _is_confident_batted_ball_path(
    ball_path: str | None, animation_profile: str | None
) -> bool:
    """Mirror of the frontend `hasConfidentBattedBallPath` gate.

    Returns True only when the ball path is a real batted-ball arc and the
    animation profile is not a no-contact profile. Keeping the truth here
    means the backend can publish a single boolean and the renderer doesn't
    need to re-derive it from `ballPath`/`animationProfile`.
    """
    if not ball_path or ball_path in ("none", "pitch"):
        return False
    if animation_profile in ("walk", "strikeout", "stolen_base"):
        return False
    return (
        ball_path == "popup"
        or ball_path.startswith("ground_")
        or ball_path.startswith("line_")
        or ball_path.startswith("fly_")
        or ball_path.startswith("foul")
        or ball_path.startswith("home_run_")
    )


def display_hint_fields(
    event: str | None,
    ball_path: str | None,
    animation_profile: str | None,
) -> tuple[bool, str | None, bool]:
    """Compute `(showBattedBallOverlay, hitLocation, suppressMovementLines)`.

    `hitLocation` is the trajectory zone whenever the backend has one — kept
    even when the overlay is suppressed so analytics/debug surfaces can read
    it. `suppressMovementLines` is True for plays whose path is non-None but
    represents a throw or pitch trajectory rather than a hit (catcher-to-home
    on a caught stealing, dropped third strike, throwing errors).
    """
    show_overlay = _is_confident_batted_ball_path(ball_path, animation_profile)
    hit_location = ball_path if ball_path not in (None, "none", "pitch") else None
    if event in _NON_BATTED_BALL_EVENTS:
        suppress = True
    elif event == "error" and ball_path and ball_path.startswith("ground_") and not show_overlay:
        # Throwing-error guard: the path is a throw to a base, not a hit.
        suppress = True
    else:
        suppress = not show_overlay
    return show_overlay, hit_location, suppress


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

__all__ = [
    "ball_path_from_event",
    "classify_animation_profile",
    "display_hint_fields",
]
