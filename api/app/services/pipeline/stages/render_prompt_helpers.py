"""Pure computational helpers for render prompt building.

These are stateless functions with no prompt text or OpenAI references.
Used by render_prompts.py to format context lines and detect game patterns.
"""

from __future__ import annotations

import re
from typing import Any

from .game_stats_helpers import _extract_last_name, compute_lead_context


def detect_game_winning_play(
    resolution_block: dict[str, Any],
    pbp_events: list[dict[str, Any]],
    home_team: str,
    away_team: str,
    league_code: str,
) -> str | None:
    """Detect if the game ended on a dramatic final-seconds play.

    Scans PBP events in the RESOLUTION block for a go-ahead or
    game-tying-then-winning score in the final 15 seconds (or at 0:00).
    Returns a prompt hint string like:
      "GAME-WINNER: Arizona's Jaden Bradley hit the go-ahead shot at 0:00 (buzzer beater)"
    or None if no dramatic finish detected.
    """
    final_score = resolution_block.get("score_after", [0, 0])
    final_margin = abs(final_score[0] - final_score[1])

    # Only look for game-winners in close finishes (margin <= 5)
    if final_margin > 5:
        return None

    play_ids = set(resolution_block.get("play_ids", []))
    if not play_ids:
        return None

    # Get the last period of the game
    period_end = resolution_block.get("period_end", 1)

    # Find scoring plays in the final period that are in this block
    candidates: list[dict[str, Any]] = []
    for evt in pbp_events:
        if evt.get("play_index") not in play_ids:
            continue
        if evt.get("period", 0) != period_end:
            continue
        # Must be a scoring play (score changed from previous)
        home_s = evt.get("home_score", 0)
        away_s = evt.get("away_score", 0)
        if home_s == 0 and away_s == 0:
            continue
        candidates.append(evt)

    if not candidates:
        return None

    # Sort by play_index descending to find the last scoring play
    candidates.sort(key=lambda e: e.get("play_index", 0), reverse=True)

    # Check the last few plays for game-winning characteristics
    for evt in candidates[:3]:
        clock = evt.get("game_clock", "")
        desc = evt.get("description", "")
        home_s = evt.get("home_score", 0)
        away_s = evt.get("away_score", 0)

        # Parse clock to seconds
        clock_secs = _parse_clock_seconds(clock)
        if clock_secs is None:
            continue

        # Only care about plays in the final 15 seconds
        if clock_secs > 15:
            continue

        # Check if this play created or changed the lead
        # (go-ahead, game-tying, or winning score)
        is_final_score = (home_s == final_score[0] and away_s == final_score[1])
        if not is_final_score:
            continue

        # This is the play that produced the final score in the last 15 seconds
        scorer = evt.get("player_name", "")

        # Clean up play description for the hint
        clean_desc = re.sub(r"^\[([^\]]+)\]\s*", "", desc)
        clean_desc = re.sub(r"\b\d+'(?![a-zA-Z])\s*", "", clean_desc)

        is_buzzer = clock_secs == 0
        clock_label = "at the buzzer" if is_buzzer else f"with {clock} remaining"

        parts = ["GAME-WINNING PLAY:"]
        if scorer:
            parts.append(f"{scorer} scored {clock_label}")
        else:
            parts.append(f"Scoring play {clock_label}")
        if clean_desc:
            parts.append(f"({clean_desc})")

        # Was the game tied just before this play?
        # Check the previous scoring state
        prev_margin = _get_pre_play_margin(evt, pbp_events)
        if prev_margin == 0:
            if is_buzzer:
                parts.append("— BUZZER BEATER to break a tie")
            else:
                parts.append("— broke the tie in the final seconds")
        elif is_buzzer:
            parts.append("— buzzer beater")

        return " ".join(parts)

    return None


def _parse_clock_seconds(clock: str | None) -> int | None:
    """Parse a game clock string like '0:15' or '00:00' to total seconds."""
    if not clock:
        return None
    # Handle formats like "0:15", "00:00", "1:30", "PT0M15S"
    match = re.match(r"^(\d+):(\d+)$", str(clock).strip())
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    # Handle "0" or "0.0"
    try:
        val = float(str(clock).strip())
        return int(val)
    except (ValueError, TypeError):
        return None


def _get_pre_play_margin(
    play: dict[str, Any],
    pbp_events: list[dict[str, Any]],
) -> int | None:
    """Find the score margin just before a given play.

    Looks at the previous play in the same period to determine
    what the score was before this play happened.
    """
    play_idx = play.get("play_index", -1)
    period = play.get("period", 0)

    # Find the previous play with a score in the same period
    prev_home = None
    prev_away = None
    for evt in pbp_events:
        if evt.get("period") != period:
            continue
        if evt.get("play_index", -1) >= play_idx:
            continue
        h = evt.get("home_score")
        a = evt.get("away_score")
        if h is not None and a is not None:
            prev_home = h
            prev_away = a

    if prev_home is not None and prev_away is not None:
        return abs(prev_home - prev_away)
    return None


def _format_lead_line(
    score_before: list[int],
    score_after: list[int],
    home_team: str,
    away_team: str,
) -> str | None:
    """Format a lead/margin context line for a block prompt.

    Returns a string like "Lead: Hawks extend the lead to 8" or None
    if there was no scoring change in the block.
    """
    ctx = compute_lead_context(score_before, score_after, home_team, away_team)
    desc = ctx.get("margin_description")
    if not desc:
        return None

    lead_after = ctx["lead_after"]
    lead_before = ctx["lead_before"]

    # Determine which team drove the scoring change
    actor = home_team if lead_after > lead_before else away_team

    return f"Lead: {actor} {desc}"


def _format_contributors_line(
    mini_box: dict[str, Any] | None,
    league_code: str,
) -> str | None:
    """Format a contributors line from block mini_box data, grouped by team.

    Reads blockStars and matches to player delta stats.
    NBA/NCAAB: "Contributors: Hawks — Young +8 pts | Celtics — Tatum +5 pts"
    NHL: "Contributors: Bruins — Pastrnak +1g/+1a, Marchand +1g"

    Returns None if mini_box is None, empty, or has no block stars.
    """
    if not mini_box:
        return None

    block_stars = mini_box.get("blockStars", [])
    if not block_stars:
        return None

    block_stars_set = set(block_stars)

    # Build per-side lookup: last_name -> (player_dict, team_name)
    side_parts: dict[str, list[str]] = {}  # team_name -> stat strings
    for side in ("home", "away"):
        team_data = mini_box.get(side, {})
        team_name = team_data.get("team", side.capitalize())
        for player in team_data.get("players", []):
            name = player.get("name", "")
            last_name = _extract_last_name(name)
            if last_name not in block_stars_set:
                continue

            stat_str = _format_player_stat(last_name, player, league_code)
            if stat_str:
                side_parts.setdefault(team_name, []).append(stat_str)

    if not side_parts:
        return None

    # Join per-team groups with " | "
    team_sections = [
        f"{team} \u2014 {', '.join(stats)}"
        for team, stats in side_parts.items()
    ]
    return f"Contributors: {' | '.join(team_sections)}"


def _format_player_stat(
    last_name: str,
    player: dict[str, Any],
    league_code: str,
) -> str | None:
    """Format a single player's stat string for the contributors line."""
    if league_code == "MLB":
        r = player.get("deltaRuns", 0)
        rbi = player.get("deltaRbi", 0)
        h = player.get("deltaHits", 0)
        stat_parts = []
        if r:
            stat_parts.append(f"+{r}R")
        if rbi:
            stat_parts.append(f"+{rbi}RBI")
        if h:
            stat_parts.append(f"+{h}H")
        if stat_parts:
            return f"{last_name} {'/'.join(stat_parts)}"
    elif league_code == "NHL":
        g = player.get("deltaGoals", 0)
        a = player.get("deltaAssists", 0)
        stat_parts = []
        if g:
            stat_parts.append(f"+{g}g")
        if a:
            stat_parts.append(f"+{a}a")
        if stat_parts:
            return f"{last_name} {'/'.join(stat_parts)}"
    else:  # NBA / NCAAB
        delta_pts = player.get("deltaPts", 0)
        if delta_pts:
            return f"{last_name} +{delta_pts} pts"
    return None


def _build_period_label(league_code: str, period_start: int, period_end: int) -> str:
    """Build sport-appropriate period label.

    Args:
        league_code: Sport code (NBA, NHL, NCAAB, MLB)
        period_start: Starting period number
        period_end: Ending period number

    Returns:
        Period label string (e.g., "Q1", "P2-P3", "H1", "OT")
    """
    period_start = max(period_start, 1)  # Guard against period=0 from bad data
    period_end = max(period_end, 1)

    def _mlb_ordinal(n: int) -> str:
        ordinals = {1: "1st", 2: "2nd", 3: "3rd"}
        return ordinals.get(n, f"{n}th")

    if league_code == "MLB":
        if period_start == period_end:
            if period_start <= 9:
                return _mlb_ordinal(period_start)
            else:
                return f"{_mlb_ordinal(period_start)} (extra)"
        else:
            return f"{_mlb_ordinal(period_start)}-{_mlb_ordinal(period_end)}"
    elif league_code == "NHL":
        if period_start == period_end:
            if period_start <= 3:
                return f"P{period_start}"
            elif period_start == 4:
                return "OT"
            elif period_start == 5:
                return "SO"
            else:
                return f"OT{period_start - 4}"
        else:
            return f"P{period_start}-P{period_end}"
    elif league_code == "NCAAB":
        if period_start == period_end:
            if period_start <= 2:
                return f"H{period_start}"
            else:
                return f"OT{period_start - 2}"
        else:
            return f"H{period_start}-H{period_end}"
    else:  # NBA
        if period_start == period_end:
            if period_start <= 4:
                return f"Q{period_start}"
            else:
                return f"OT{period_start - 4}"
        else:
            return f"Q{period_start}-Q{period_end}"
