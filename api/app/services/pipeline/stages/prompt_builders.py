"""Prompt construction for OpenAI narrative generation.

This module builds prompts for the OpenAI API to generate moment narratives.
"""

from __future__ import annotations

import re
from typing import Any

from .game_stats_helpers import (
    compute_lead_context,
    compute_running_player_stats,
    format_player_stat_hint,
)


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_prompt_field(text: str, max_len: int = 200) -> str:
    """Strip control characters and newlines before inserting into an LLM prompt.

    Prevents injected delimiter sequences (---MOMENT X--- / ---END MOMENT X---) or
    instruction overrides embedded in DB-sourced strings from escaping their field slot.
    """
    text = text.replace("\n", " ").replace("\r", " ")
    text = _CONTROL_CHARS_RE.sub("", text)
    return text[:max_len]


def _format_period(period: int, league_code: str = "NBA") -> str:
    """Format period for display based on league.

    Args:
        period: Period number (1, 2, 3, etc.)
        league_code: League code (NBA, NCAAB, NHL, etc.)

    Returns:
        Formatted period string (Q1-Q4, H1-H2, P1-P3, OT, SO, etc.)
    """
    period = max(period, 1)  # Guard against period=0 from bad data

    if league_code == "MLB":
        ordinals = {1: "1st", 2: "2nd", 3: "3rd"}
        label = ordinals.get(period, f"{period}th")
        if period > 9:
            return f"{label} (extra)"
        return label
    if league_code == "NHL":
        if period <= 3:
            return f"P{period}"  # P1, P2, P3
        if period == 4:
            return "OT"
        if period == 5:
            return "SO"  # Shootout
        return f"OT{period - 3}"  # Extended OT (playoffs): OT2, OT3, etc.
    if league_code == "NCAAB":
        if period <= 2:
            return f"H{period}"
        return f"OT{period - 2}"
    # NBA/default: quarters
    if period <= 4:
        return f"Q{period}"
    return f"OT{period - 4}"


def build_batch_prompt(
    moments_batch: list[tuple[int, dict[str, Any], list[dict[str, Any]]]],
    game_context: dict[str, str],
    is_retry: bool = False,
    all_pbp_events: list[dict[str, Any]] | None = None,
) -> str:
    """Build an OpenAI prompt for a batch of moments.

    Generates 2-3 paragraph narratives (6-10 sentences) that describe
    the full sequence of gameplay within each moment.

    Args:
        moments_batch: List of (moment_index, moment, moment_plays) tuples
        game_context: Team names and sport info
        is_retry: Whether this is a retry after validation failure
        all_pbp_events: Full PBP event list for computing running stats

    Returns:
        Prompt string for OpenAI to generate all narratives in the batch
    """
    home_team = _sanitize_prompt_field(game_context.get("home_team_name", "Home"), 60)
    away_team = _sanitize_prompt_field(game_context.get("away_team_name", "Away"), 60)
    player_names = game_context.get("player_names", {})
    league_code = game_context.get("sport", "NBA")

    # Build player name reference for the prompt (abbrev -> full name)
    name_mappings = []
    for abbrev, full in player_names.items():
        if ". " in abbrev:  # Only abbreviated forms like "D. Mitchell"
            safe_abbrev = _sanitize_prompt_field(abbrev, 30)
            safe_full = _sanitize_prompt_field(full, 60)
            name_mappings.append(f"{safe_abbrev}={safe_full}")

    # Limit to avoid bloating prompt
    name_ref = ", ".join(name_mappings[:40]) if name_mappings else ""

    # Build compact moments data with contextual stats
    moments_lines = []
    for moment_index, moment, moment_plays in moments_batch:
        period = moment.get("period", 1)
        clock = moment.get("start_clock", "")
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])
        explicitly_narrated = set(moment.get("explicitly_narrated_play_ids", []))

        # Compute lead context for this moment
        lead_ctx = compute_lead_context(score_before, score_after, home_team, away_team)

        # Compute running player stats if PBP events are available
        player_hints = []
        if all_pbp_events and moment_plays:
            first_play_idx = min(
                (p.get("play_index", 0) for p in moment_plays), default=0
            )
            running_stats = compute_running_player_stats(
                all_pbp_events, first_play_idx - 1
            )
            # Get hints for players in this moment
            moment_players = {p.get("player_name") for p in moment_plays if p.get("player_name")}
            for player in moment_players:
                if player in running_stats:
                    hint = format_player_stat_hint(player, running_stats[player])
                    if hint:
                        player_hints.append(hint)

        # Compact play format: just the essentials
        plays_compact = []
        for play in moment_plays:
            play_index = play.get("play_index")
            is_explicit = play_index in explicitly_narrated
            star = "*" if is_explicit else ""
            desc = _sanitize_prompt_field(play.get("description") or "", 100)
            plays_compact.append(f"{star}{desc}")

        plays_str = "; ".join(plays_compact)
        score_change = ""
        if score_after != score_before:
            score_change = f" → {away_team} {score_after[0]}-{score_after[1]} {home_team}"

        # Build context line with lead info and player stats
        context_parts = []
        if lead_ctx.get("margin_description"):
            context_parts.append(f"Lead: {lead_ctx['margin_description']}")
        if player_hints:
            context_parts.append(f"Stats: {'; '.join(player_hints[:3])}")

        context_line = f" [{', '.join(context_parts)}]" if context_parts else ""

        # Use clear boundary format to prevent AI from mixing up plays
        period_str = _format_period(period, league_code)
        moments_lines.append(
            f"---MOMENT {moment_index}---\n"
            f"{period_str} {clock} | {away_team} {score_before[0]}-{score_before[1]} {home_team}{score_change}{context_line}\n"
            f"PLAYS FOR THIS MOMENT ONLY: {plays_str}\n"
            f"---END MOMENT {moment_index}---"
        )

    moments_block = "\n".join(moments_lines)

    # Build prompt with player name rule
    name_rule = "- FULL NAME on first mention (e.g., \"Donovan Mitchell\"), LAST NAME only after. NEVER use initials like \"D. Mitchell\"."
    if name_ref:
        name_rule += f"\n  Names: {name_ref}"

    # Retry prompt is more explicit about requirements
    if is_retry:
        retry_warning = "\n\nIMPORTANT: Previous response failed validation. Ensure:\n- Each narrative is 2-3 paragraphs (6-10 sentences total)\n- All *starred plays are mentioned\n- No subjective adjectives (huge, dominant, electric)\n- No speculation about intent or psychology\n"
    else:
        retry_warning = ""

    # Style guidance for retry prompts
    if is_retry:
        style_emphasis = """
STYLE (must sound natural when read aloud):
- Vary sentence length (mix short and longer sentences)
- Don't start multiple sentences the same way
- Lead with actions, not statistics
- Avoid templated patterns like "X scored, then Y answered" repeated"""
    else:
        style_emphasis = ""

    prompt = f"""Write 2-3 paragraph recaps (6-10 sentences total) for each moment. {away_team} vs {home_team}.
{retry_warning}
CRITICAL: Each moment has its own plays listed between ---MOMENT X--- markers.
ONLY describe the plays listed for THAT specific moment. Do NOT include plays from other moments.

STRUCTURE EACH MOMENT'S NARRATIVE:
- Paragraph 1: Set the scene, opening action, initial plays
- Paragraph 2: Key plays, responses, back-and-forth action
- Paragraph 3: Resolution, score state, outcome

RULES:
- 6-10 sentences per moment across 2-3 paragraphs, flowing like broadcast commentary
- ONLY describe plays listed in "PLAYS FOR THIS MOMENT ONLY" section
- Mention *starred plays by player name - integrate them naturally into the narrative flow
- Use [Lead:] context naturally (e.g., "extending the lead to 8", "cutting the deficit to 3")
- Use [Stats:] context when notable (e.g., "his third three of the quarter")
{name_rule}
- TEAM ATTRIBUTION: On first mention of each player, tie them to their team naturally. Vary the style:
  * "Miami's Bam Adebayo" or "Chicago's Jalen Smith" (possessive)
  * "Adebayo for Miami" or "Smith for Chicago" (scoring context)
  * After first mention, just use last name
  * Don't use parentheses like "(MIA)" - keep it broadcast-style

PARAGRAPH BREAKS: Use \\n\\n between paragraphs for natural flow. Each paragraph should cover a phase of the action.

AVOID: momentum, turning point, dominant, electric, huge, clutch, crowd erupted, wanted to, felt
{style_emphasis}
{moments_block}

Return JSON - use the EXACT moment number from each ---MOMENT X--- marker:
{{"items":[{{"i":0,"n":"Multi-paragraph narrative for moment 0 ONLY"}},{{"i":1,"n":"Multi-paragraph narrative for moment 1 ONLY"}}...]}}"""

    return prompt


def build_moment_prompt(
    moment: dict[str, Any],
    moment_plays: list[dict[str, Any]],
    game_context: dict[str, str],
    moment_index: int,
    is_retry: bool = False,
) -> str:
    """Build the OpenAI prompt for a single moment.

    Generates broadcast-style recaps that summarize the action.

    Args:
        moment: The moment data
        moment_plays: PBP events for the moment
        game_context: Team names and sport info
        moment_index: Index of this moment
        is_retry: Whether this is a retry after validation failure

    Returns:
        Prompt string for OpenAI
    """
    home_team = _sanitize_prompt_field(game_context.get("home_team_name", "Home"), 60)
    away_team = _sanitize_prompt_field(game_context.get("away_team_name", "Away"), 60)
    player_names = game_context.get("player_names", {})
    league_code = game_context.get("sport", "NBA")

    period = moment.get("period", 1)
    clock = moment.get("start_clock", "")
    score_before = moment.get("score_before", [0, 0])
    score_after = moment.get("score_after", [0, 0])
    explicitly_narrated = set(moment.get("explicitly_narrated_play_ids", []))

    # Compute scoring context
    away_pts = score_after[0] - score_before[0]
    home_pts = score_after[1] - score_before[1]
    lead_after = score_after[1] - score_after[0]  # positive = home leads

    # Build play descriptions
    plays_desc = []
    for play in moment_plays:
        play_index = play.get("play_index")
        is_explicit = play_index in explicitly_narrated
        marker = "*" if is_explicit else ""
        desc = _sanitize_prompt_field(play.get("description") or "No description", 200)
        plays_desc.append(f"  {marker}{desc}")

    plays_block = "\n".join(plays_desc)

    # Player name mappings
    name_mappings = []
    for abbrev, full in player_names.items():
        if ". " in abbrev:
            safe_abbrev = _sanitize_prompt_field(abbrev, 30)
            safe_full = _sanitize_prompt_field(full, 60)
            name_mappings.append(f"{safe_abbrev}={safe_full}")
    name_ref = ", ".join(name_mappings[:30]) if name_mappings else ""

    name_rule = "Use FULL NAME on first mention, LAST NAME only after."
    if name_ref:
        name_rule += f" Names: {name_ref}"

    if is_retry:
        retry_note = "\n\nPREVIOUS RESPONSE FAILED. Mention all *starred plays by player name.\n"
    else:
        retry_note = ""

    # Build margin context
    if lead_after > 0:
        margin_ctx = f"{home_team} leads by {lead_after}"
    elif lead_after < 0:
        margin_ctx = f"{away_team} leads by {abs(lead_after)}"
    else:
        margin_ctx = "Game tied"

    period_str = _format_period(period, league_code)
    prompt = f"""Write a broadcast-style recap (2-3 paragraphs, 6-10 sentences total). {away_team} vs {home_team}.
{retry_note}
{period_str} at {clock}
Score: {away_team} {score_before[1]}-{score_before[0]} {home_team} → {away_team} {score_after[1]}-{score_after[0]} {home_team}
Scoring: {away_team} +{away_pts}, {home_team} +{home_pts}. {margin_ctx}.

Plays:
{plays_block}

Write like a broadcaster giving detailed game action:
- Paragraph 1: Set the scene and opening action
- Paragraph 2: Key plays and back-and-forth
- Paragraph 3: Resolution and score state
- Mention *starred players naturally, integrating them into the flow
- {name_rule}
- Tie players to their team on first mention (e.g., "Miami's Adebayo", "Smith for Chicago") - no parentheses
- Use \\n\\n between paragraphs

FORBIDDEN: dominant, electric, huge, momentum, turning point, wanted to, felt

Respond with ONLY the recap text (2-3 paragraphs)."""

    return prompt
