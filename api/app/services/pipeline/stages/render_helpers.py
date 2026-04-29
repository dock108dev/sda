"""Helper functions for RENDER_BLOCKS stage.

Contains overtime detection and mention injection.
"""

from __future__ import annotations

from typing import Any


def detect_overtime_info(
    block: dict[str, Any],
    league_code: str = "NBA",
) -> dict[str, Any]:
    """Detect if a block involves overtime or shootout periods.

    Args:
        block: Block dict with period_start and period_end
        league_code: Sport code (NBA, NHL, NCAAB)

    Returns:
        Dict with overtime info:
        - has_overtime: bool - block includes OT periods
        - enters_overtime: bool - block transitions FROM regulation TO OT
        - is_shootout: bool - NHL shootout period
        - ot_label: str - Label like "OT", "OT1", "OT2", "SO"
        - regulation_end_period: int - Last regulation period for this sport
    """
    period_start = block.get("period_start", 1)
    period_end = block.get("period_end", period_start)

    # Determine regulation end period by sport
    if league_code == "MLB":
        regulation_end = 9  # MLB has 9 innings
    elif league_code == "NHL":
        regulation_end = 3  # NHL has 3 periods
    elif league_code == "NCAAB":
        regulation_end = 2  # NCAAB has 2 halves
    else:
        regulation_end = 4  # NBA has 4 quarters

    has_overtime = period_end > regulation_end
    enters_overtime = period_start <= regulation_end and period_end > regulation_end

    # NHL period structure:
    # - Regular season: Period 4 = OT (5 min), Period 5 = Shootout
    # - Playoffs: Period 4 = OT1, Period 5 = OT2, Period 6 = OT3, etc. (no shootout)
    # We don't have season_type here, so we assume regular season structure.
    is_shootout = league_code == "NHL" and period_end == 5

    # Generate OT label
    ot_label = ""
    if has_overtime:
        if is_shootout:
            ot_label = "shootout"
        elif league_code == "MLB":
            ot_label = "extra innings"
        elif league_code == "NHL":
            ot_label = "overtime"
        else:
            # NBA/NCAAB: OT1 = period 5 (NBA) or period 3 (NCAAB)
            ot_num = period_end - regulation_end
            ot_label = f"OT{ot_num}" if ot_num > 1 else "overtime"

    return {
        "has_overtime": has_overtime,
        "enters_overtime": enters_overtime,
        "is_shootout": is_shootout,
        "ot_label": ot_label,
        "regulation_end_period": regulation_end,
    }


def check_overtime_mention(
    narrative: str,
    ot_info: dict[str, Any],
    league_code: str = "NBA",
) -> bool:
    """Check if narrative properly mentions overtime/shootout.

    Args:
        narrative: The narrative text
        ot_info: Overtime info dict from detect_overtime_info
        league_code: Sport code (NBA, MLB, NHL, NCAAB)

    Returns:
        True if OT is mentioned or not required, False if missing required mention
    """
    if not ot_info.get("enters_overtime"):
        return True  # No OT transition = no mention required

    narrative_lower = narrative.lower()

    # Check for various OT mention patterns
    ot_patterns = [
        "overtime",
        "extra period",
        " ot ",
        " ot.",
        " ot,",
        "goes to ot",
        "headed to ot",
        "forcing ot",
        "required ot",
        "sending it to",
        "took overtime",
        "into overtime",
    ]

    # NHL-specific patterns
    if ot_info.get("is_shootout"):
        ot_patterns.extend(["shootout", "shoot out", "shoot-out"])

    # MLB-specific patterns
    if league_code == "MLB":
        ot_patterns.extend([
            "extra inning",
            "extras",
            "went to the 10th",
            "went to the 11th",
            "10th inning",
            "11th inning",
            "12th inning",
        ])

    return any(pattern in narrative_lower for pattern in ot_patterns)


def inject_overtime_mention(
    narrative: str,
    ot_info: dict[str, Any],
    league_code: str = "NBA",
) -> str:
    """Inject overtime mention into narrative if missing.

    Args:
        narrative: The narrative text
        ot_info: Overtime info from detect_overtime_info
        league_code: Sport code (NBA, MLB, NHL, NCAAB)

    Returns:
        Narrative with OT mention injected if it was missing
    """
    if not ot_info.get("enters_overtime"):
        return narrative

    if check_overtime_mention(narrative, ot_info, league_code):
        return narrative  # Already has mention

    # Inject OT mention at the end
    narrative = narrative.rstrip()
    if not narrative.endswith("."):
        narrative += "."

    if ot_info.get("is_shootout"):
        injection = " The game headed to a shootout to determine the winner."
    elif league_code == "MLB":
        injection = " The game went to extra innings."
    else:
        ot_label = ot_info.get("ot_label", "overtime")
        injection = f" The game headed to {ot_label}."

    return narrative + injection
