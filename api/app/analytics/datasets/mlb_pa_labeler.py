"""MLB plate-appearance outcome labeler.

Maps MLB Stats API at-bat event strings to canonical PA outcome labels.
These labels come from the ``result.event`` field in the PBP playByPlay
endpoint response.

Canonical outcomes:
- strikeout
- walk_or_hbp
- single
- double
- triple
- home_run
- ball_in_play_out
"""

from __future__ import annotations

# Canonical PA outcome labels
PA_OUTCOME_LABELS: list[str] = [
    "strikeout",
    "walk_or_hbp",
    "single",
    "double",
    "triple",
    "home_run",
    "ball_in_play_out",
]

# Mapping from MLB Stats API event names to canonical labels.
# Keys are lowercased versions of result.event or result.eventType.
_EVENT_MAP: dict[str, str] = {
    # Strikeouts
    "strikeout": "strikeout",
    "strikeout - dp": "strikeout",
    "strikeout_double_play": "strikeout",
    "strikeout - tp": "strikeout",
    "strikeout_triple_play": "strikeout",
    # Walks / HBP
    "walk": "walk_or_hbp",
    "intent_walk": "walk_or_hbp",
    "intentional_walk": "walk_or_hbp",
    "hit_by_pitch": "walk_or_hbp",
    # Hits
    "single": "single",
    "double": "double",
    "triple": "triple",
    "home_run": "home_run",
    # Outs on balls in play
    "groundout": "ball_in_play_out",
    "ground_out": "ball_in_play_out",
    "flyout": "ball_in_play_out",
    "fly_out": "ball_in_play_out",
    "lineout": "ball_in_play_out",
    "line_out": "ball_in_play_out",
    "pop out": "ball_in_play_out",
    "pop_out": "ball_in_play_out",
    "forceout": "ball_in_play_out",
    "force_out": "ball_in_play_out",
    "grounded_into_double_play": "ball_in_play_out",
    "grounded into dp": "ball_in_play_out",
    "double_play": "ball_in_play_out",
    "triple_play": "ball_in_play_out",
    "fielders_choice": "ball_in_play_out",
    "fielders choice": "ball_in_play_out",
    "fielders_choice_out": "ball_in_play_out",
    "field_out": "ball_in_play_out",
    "sac_fly": "ball_in_play_out",
    "sac_bunt": "ball_in_play_out",
    "sacrifice_fly": "ball_in_play_out",
    "sacrifice_bunt": "ball_in_play_out",
    "sac fly": "ball_in_play_out",
    "sac bunt": "ball_in_play_out",
    "bunt_groundout": "ball_in_play_out",
    "bunt_ground_out": "ball_in_play_out",
    "bunt_pop_out": "ball_in_play_out",
    "bunt_lineout": "ball_in_play_out",
    "bunt_line_out": "ball_in_play_out",
    "field_error": "ball_in_play_out",  # Reached on error — treat as BIP out for modeling
}

# Events that are not plate appearances (should be skipped)
_NON_PA_EVENTS: set[str] = {
    "stolen_base",
    "caught_stealing",
    "wild_pitch",
    "passed_ball",
    "balk",
    "pickoff",
    "pickoff_1b",
    "pickoff_2b",
    "pickoff_3b",
    "runner_double_play",
    "other_advance",
    "game_advisory",
    "ejection",
    "catcher_interf",
    "fan_interference",
    "",
}


def label_pa_event(event_str: str) -> str | None:
    """Map an MLB Stats API event string to a canonical PA outcome.

    Returns None if the event is not a plate appearance (e.g., stolen base,
    wild pitch, pickoff) or is unrecognized.
    """
    if not event_str:
        return None

    normalized = event_str.lower().strip().replace(" ", "_")

    # Check direct mapping first
    label = _EVENT_MAP.get(normalized)
    if label:
        return label

    # Try with spaces instead of underscores
    with_spaces = event_str.lower().strip()
    label = _EVENT_MAP.get(with_spaces)
    if label:
        return label

    # Check if it's a known non-PA event
    if normalized in _NON_PA_EVENTS:
        return None

    # Fuzzy matching for common patterns
    if "strikeout" in normalized:
        return "strikeout"
    if "walk" in normalized:
        return "walk_or_hbp"
    if "home_run" in normalized or "homer" in normalized:
        return "home_run"
    if "single" in normalized:
        return "single"
    if "double" in normalized and "play" not in normalized:
        return "double"
    if "triple" in normalized and "play" not in normalized:
        return "triple"
    if any(x in normalized for x in ("out", "fly", "ground", "line", "pop", "force", "field")):
        return "ball_in_play_out"

    # Unknown event — skip it
    return None
