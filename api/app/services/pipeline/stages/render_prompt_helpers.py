"""Pure computational helpers for render prompt building.

These are stateless functions with no prompt text or OpenAI references.
Used by render_prompts.py to format context lines and detect game patterns.
"""

from __future__ import annotations

from typing import Any

from .game_stats_helpers import _extract_last_name, compute_lead_context


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


def _detect_close_game(blocks: list[dict[str, Any]]) -> tuple[bool, int]:
    """Detect if a game is close based on block score margins.

    Returns:
        Tuple of (is_close_game, max_margin_seen)
    """
    max_margin = 0
    for block in blocks:
        score_before = block.get("score_before", [0, 0])
        score_after = block.get("score_after", [0, 0])
        margin_before = abs(score_before[0] - score_before[1])
        margin_after = abs(score_after[0] - score_after[1])
        block_peak = block.get("peak_margin", 0)
        max_margin = max(max_margin, margin_before, margin_after, block_peak)
    # A game where no team ever led by more than 7 is a tight contest
    return max_margin <= 7, max_margin


def _detect_big_lead_comeback(
    blocks: list[dict[str, Any]],
) -> tuple[bool, int, int]:
    """Detect if a game had a big lead that was overcome (comeback).

    A comeback = peak_margin >= 15 AND final_margin < peak_margin * 0.5

    Returns:
        Tuple of (is_comeback, game_peak_margin, final_margin)
    """
    game_peak_margin = 0
    for block in blocks:
        # Check block-level peak_margin field
        block_peak = block.get("peak_margin", 0)
        if block_peak > game_peak_margin:
            game_peak_margin = block_peak
        # Also check boundary scores
        score_before = block.get("score_before", [0, 0])
        score_after = block.get("score_after", [0, 0])
        for s in (score_before, score_after):
            margin = abs(s[0] - s[1])
            if margin > game_peak_margin:
                game_peak_margin = margin

    # Final margin from the last block
    last_block = blocks[-1] if blocks else {}
    final_score = last_block.get("score_after", [0, 0])
    final_margin = abs(final_score[0] - final_score[1])

    is_comeback = game_peak_margin >= 15 and final_margin < game_peak_margin * 0.5
    return is_comeback, game_peak_margin, final_margin


def _build_period_label(league_code: str, period_start: int, period_end: int) -> str:
    """Build sport-appropriate period label.

    Args:
        league_code: Sport code (NBA, NHL, NCAAB, MLB)
        period_start: Starting period number
        period_end: Ending period number

    Returns:
        Period label string (e.g., "Q1", "P2-P3", "H1", "OT")
    """
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
