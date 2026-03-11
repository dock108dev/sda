"""Prompt building functions for RENDER_BLOCKS stage.

Contains prompt templates and builders for OpenAI calls.
Pure computational helpers are in render_prompt_helpers.py.
"""

from __future__ import annotations

import re
from typing import Any

from .render_helpers import detect_overtime_info
from .render_prompt_helpers import (
    _build_period_label,
    _detect_big_lead_comeback,
    _detect_close_game,
    _format_contributors_line,
    _format_lead_line,
)
from .render_validation import FORBIDDEN_WORDS

# Game-level flow pass prompt - intentionally tight and low-token
GAME_FLOW_PASS_PROMPT = """You are given the full Game Flow for a single game as a sequence of blocks.

Each block is already correct and final in structure, timing, and scoring.
Your job is to rewrite for narrative coherence so the blocks flow naturally
as a single game recap, while keeping each block as its own paragraph.

Rules:
- Preserve block order and boundaries
- Preserve scores, players, and chronology. You may restructure sentences for flow.
- Do not change scores or periods
- Each block should be 1-5 sentences in one paragraph
- Improve flow, reduce repetition, and acknowledge the passage of time across blocks
- No hype, no speculation, no raw play-by-play
- SETUP blocks must NOT foreshadow the outcome. Write as if the game is still unfolding.
- RESPONSE blocks must reflect an actual scoring change. If the score didn't move, describe the state, not a "response."
- Give each half/period proportional narrative weight. Don't compress late-game action into a throwaway line.
- If a trailing team never got within single digits, don't call it a "comeback" — call it a rally that fell short.
- Ensure player names appear in full only on first mention across the entire flow. Use last name thereafter.
- Use full team name only once early. Rotate between short name and pronoun.
- CRITICAL: If the game goes to overtime/OT/shootout, the narrative MUST mention this transition
  (e.g., "the game headed to overtime", "forcing an extra period", "sending it to OT")

If a block already flows well, make minimal changes.

Return JSON: {"blocks": [{"i": block_index, "n": "revised narrative"}]}"""


def build_game_flow_pass_prompt(
    blocks: list[dict[str, Any]],
    game_context: dict[str, str],
) -> str:
    """Build prompt for game-level flow pass.

    This is a single call that receives all blocks and smooths transitions
    while preserving facts, scores, and structure.

    Args:
        blocks: List of block dicts with narratives already generated
        game_context: Team names and context

    Returns:
        Prompt string for the flow pass
    """
    home_team = game_context.get("home_team_name", "Home")
    away_team = game_context.get("away_team_name", "Away")
    league_code = game_context.get("sport", "NBA")

    is_close_game, max_margin = _detect_close_game(blocks)
    is_comeback, game_peak_margin, final_margin = _detect_big_lead_comeback(blocks)

    prompt_parts = [
        GAME_FLOW_PASS_PROMPT,
        "",
        f"Game: {away_team} at {home_team}",
    ]

    score_unit = "runs" if league_code == "MLB" else "pts"
    if is_close_game:
        prompt_parts.append(
            f"\nNOTE: Close game (max margin: {max_margin} {score_unit}). Don't overstate leads. Detail the finish."
        )

    if is_comeback:
        prompt_parts.append(
            f"\nNOTE: Comeback game (peak margin: {game_peak_margin}, final: {final_margin}). "
            f"A team led by {game_peak_margin} at one point — narrate the swing."
        )

    prompt_parts.extend([
        "",
        "BLOCKS:",
    ])

    for block in blocks:
        block_idx = block["block_index"]
        role = block.get("role", "")
        period_start = block.get("period_start", 1)
        period_end = block.get("period_end", period_start)
        score_before = block.get("score_before", [0, 0])
        score_after = block.get("score_after", [0, 0])
        narrative = block.get("narrative", "")

        # Detect overtime info
        ot_info = detect_overtime_info(block, league_code)

        # Period label (sport-aware)
        period_label = _build_period_label(league_code, period_start, period_end)

        prompt_parts.append(f"\nBlock {block_idx} ({role}, {period_label}):")
        prompt_parts.append(
            f"Score: {away_team} {score_before[1]}-{score_before[0]} {home_team} "
            f"-> {away_team} {score_after[1]}-{score_after[0]} {home_team}"
        )

        # Add OT flag if this block enters overtime
        if ot_info["enters_overtime"]:
            prompt_parts.append(f"*** MUST MENTION: Game goes to {ot_info['ot_label']} ***")

        # Add peak margin context for flow pass when meaningfully different
        flow_peak = block.get("peak_margin", 0)
        flow_boundary = max(abs(score_before[0] - score_before[1]),
                            abs(score_after[0] - score_after[1]))
        if flow_peak >= flow_boundary + 6:
            prompt_parts.append(f"(Peak margin in this block: {flow_peak})")

        prompt_parts.append(f"Current narrative: {narrative}")

    return "\n".join(prompt_parts)


def build_block_prompt(
    blocks: list[dict[str, Any]],
    game_context: dict[str, str],
    pbp_events: list[dict[str, Any]],
) -> str:
    """Build the prompt for generating block narratives.

    Args:
        blocks: List of block dicts (without narratives)
        game_context: Team names and other context
        pbp_events: PBP events for play descriptions

    Returns:
        Prompt string for OpenAI
    """
    home_team = game_context.get("home_team_name", "Home")
    away_team = game_context.get("away_team_name", "Away")
    home_abbrev = game_context.get("home_team_abbrev", "")
    away_abbrev = game_context.get("away_team_abbrev", "")
    league_code = game_context.get("sport", "NBA")

    # Build abbreviation -> full team name lookup for key plays
    abbrev_to_team: dict[str, str] = {}
    if home_abbrev:
        abbrev_to_team[home_abbrev.upper()] = home_team
    if away_abbrev:
        abbrev_to_team[away_abbrev.upper()] = away_team

    # Check if any block involves overtime
    has_any_overtime = any(
        detect_overtime_info(block, league_code)["has_overtime"]
        for block in blocks
    )

    # Detect close game for tone guidance
    is_close_game, max_margin = _detect_close_game(blocks)

    # Detect big lead / comeback
    is_comeback, game_peak_margin, final_margin = _detect_big_lead_comeback(blocks)

    # Build play lookup
    play_lookup: dict[int, dict[str, Any]] = {
        e["play_index"]: e for e in pbp_events if "play_index" in e
    }

    # Build player roster from PBP events
    home_players: set[str] = set()
    away_players: set[str] = set()
    for evt in pbp_events:
        name = evt.get("player_name", "")
        evt_abbrev = (evt.get("team_abbreviation") or "").upper()
        if not name or not evt_abbrev:
            continue
        if home_abbrev and evt_abbrev == home_abbrev.upper():
            home_players.add(name)
        elif away_abbrev and evt_abbrev == away_abbrev.upper():
            away_players.add(name)

    prompt_parts = [
        "Generate broadcast-quality narrative blocks for a game recap.",
        "",
        f"Teams: {away_team} (away) vs {home_team} (home)",
    ]

    # Add player roster so OpenAI has authoritative player -> team mapping
    if home_players or away_players:
        prompt_parts.append("")
        prompt_parts.append("ROSTERS:")
        if home_players:
            roster = ", ".join(sorted(home_players)[:10])
            prompt_parts.append(f"{home_team} (home): {roster}")
        if away_players:
            roster = ", ".join(sorted(away_players)[:10])
            prompt_parts.append(f"{away_team} (away): {roster}")

    prompt_parts.extend([
        "",
        "NARRATIVE STRUCTURE:",
        "- Write 1-5 sentences per block (~40-100 words). Vary length by role — RESOLUTION may be brief, DECISION_POINT may be detailed.",
        "- Each block describes a STRETCH of play, not isolated events",
        "- Connect plays with cause-and-effect",
        "- Vary sentence openings",
        "- Key plays are provided for context. Reference them when narratively important, but omission is acceptable editorial judgment.",
        "- Describe stretches and effects, not individual events. Collapse consecutive scoring into runs where appropriate.",
        "",
    ])

    # League-specific connecting phrases
    if league_code == "MLB":
        prompt_parts.extend([
            "CONNECTING PHRASES TO USE:",
            "- 'building on that', 'in response', 'shortly after'",
            "- 'over the next several at-bats', 'as the inning progressed'",
            "- 'trading runs', 'the teams exchanged leads'",
        ])
    else:
        prompt_parts.extend([
            "CONNECTING PHRASES TO USE:",
            "- 'building on that', 'in response', 'shortly after'",
            "- 'over the next several possessions', 'as the period progressed'",
            "- 'trading baskets', 'the teams exchanged leads'",
        ])

    prompt_parts.extend([
        "",
        "ROLE-SPECIFIC GUIDANCE:",
        "- SETUP: Establish tone and early shape. May contain zero specific plays. Abstraction encouraged.",
        "  * NEVER foreshadow or spoil the outcome. No 'would be', 'would prove', 'would not recover'.",
        "  * Write as if the game is unfolding — the reader doesn't know who wins yet.",
        "- MOMENTUM_SHIFT: Name the trigger, summarize the effect. Describe the run, not each play.",
        "- RESPONSE: Bridge narrative rhythm. Team-level summary preferred. Often abstract.",
        "  * A RESPONSE block MUST describe an actual scoring response or tactical adjustment.",
        "  * If the score did not change in this block, do NOT frame it as a 'response' — describe the state of play instead.",
        "- DECISION_POINT: Highest specificity. Name exact plays and players. This block earns detail.",
        "- RESOLUTION: Land the outcome. No re-narration. Final impression + score. May be the shortest block.",
        "",
        "PLAYER NAMES (CRITICAL):",
        "- Use FULL NAME on first mention (e.g., 'Donovan Mitchell', 'Brandon Miller')",
        "- NEVER use initials like 'D. Mitchell' or 'B. Miller' - always spell out first names",
        "- After first mention, use LAST NAME only (e.g., 'Mitchell', 'Miller')",
        "- Common names are fine abbreviated after first mention (Williams, Smith, Jones)",
        "- Names apply across the entire flow, not per-block. If a player was named in a previous block, use last name only.",
        "",
        "TEAM ATTRIBUTION (CRITICAL):",
        "- On FIRST mention of each player, tie them to their team naturally:",
        f"  * \"{home_team}'s [Player Name]\" or \"{away_team}'s [Player Name]\" (possessive)",
        f"  * \"[Player Name] for {home_team}\" or \"[Player Name] for {away_team}\" (scoring context)",
        "- After first mention, just use last name without team",
        "- Do NOT use parenthetical abbreviations like '(CHA)' or '(NOP)'",
        "- Full team name once in SETUP. Rotate between short name, nickname, and pronoun thereafter.",
        "- Avoid repeated 'Full Team Name's Player Name' constructions.",
        "",
        "STYLE REQUIREMENTS:",
        "- Use broadcast tone, not stat-feed prose",
        "- NO stat-listing patterns like 'X had Y points' or 'X finished with Y'",
        "- NO subjective adjectives (incredible, amazing, unbelievable, insane)",
        "- Describe ACTIONS, not statistics",
        "- Keep individual sentences concise (under 30 words each)",
        "",
        "PROPORTIONAL COVERAGE:",
        "- Give each half/period proportional narrative weight. Do NOT compress the entire second half into one brief block.",
        "- If the game was close-ish throughout, each phase deserves real coverage — not just the early action.",
        "- Late-game blocks should never feel like afterthoughts, even if the first half was more dramatic.",
        "",
        "NARRATIVE COMPRESSION:",
        "- Collapse consecutive scoring into runs (e.g., 'went on a 3-run rally')" if league_code == "MLB" else "- Collapse consecutive scoring into runs (e.g., 'went on a 12-0 run')",
        "- Use team-level descriptions for collective action",
        "- Describe momentum through state change, not event enumeration",
        "- Narrate consequences, not transactions",
        "- Omitting routine scoring detail is acceptable",
        "",
        "CONTEXTUAL DATA USAGE:",
        "- [Lead:] lines describe how the lead/deficit changed during this block",
        "  Weave naturally: 'extending the lead to 8' or 'pulling within 3'",
        "- [Peak:] lines show the largest lead WITHIN a block, even if it eroded by block's end",
        "  Use this to anchor the high-water mark: 'built a 22-point lead before...'",
        "- [Contributors:] lines show who drove the scoring in this block",
        "  Integrate naturally: mention these players' actions, not their stat lines",
        "- Do NOT quote these lines verbatim - use them as narrative fuel",
        "",
        "FORBIDDEN WORDS (do not use):",
        ", ".join(FORBIDDEN_WORDS),
        "",
    ])

    # Add league-specific sport guidance
    if league_code == "MLB":
        prompt_parts.extend([
            "BASEBALL-SPECIFIC:",
            "- Use 'innings' not 'quarters' or 'periods'",
            "- Use 'runs' not 'points'",
            "- Refer to 'at-bats', 'innings', 'pitching changes', 'defensive plays'",
            "- Late-game = 7th inning onward",
            "- Extra innings (10th+), not 'overtime'",
            "- 'went on a 3-run rally' not 'went on a 12-0 run'",
            "",
        ])

    # Add close-game-specific guidance
    score_unit = "runs" if league_code == "MLB" else "pts"
    if is_close_game:
        prompt_parts.extend([
            f"CLOSE GAME (max margin: {max_margin} {score_unit}):",
            f"- Do NOT overstate leads when margin is 1-2 {score_unit}. Emphasize back-and-forth.",
            "- RESOLUTION: Capture the tension of the finish with specificity.",
            "",
        ])

    # Add big lead / comeback guidance
    if is_comeback:
        comeback_gap = game_peak_margin - final_margin
        prompt_parts.extend([
            f"BIG LEAD / COMEBACK (peak margin: {game_peak_margin}, final: {final_margin}):",
            f"- A team led by {game_peak_margin} at one point. Do NOT describe this as a 'modest' or 'slim' lead.",
            "- If the lead eroded, narrate the comeback arc — name the swing.",
            "- Use [Peak:] data in blocks to anchor the high-water mark.",
        ])
        if comeback_gap < game_peak_margin // 2:
            prompt_parts.append(
                f"- The trailing team never got closer than {final_margin}. Do NOT oversell this as a 'comeback' — "
                f"it was a rally that fell short. Frame it as tightening, not a real threat."
            )
        prompt_parts.append("")

    # Add overtime-specific guidance if game went to OT
    if has_any_overtime:
        prompt_parts.extend([
            "OVERTIME/EXTRA PERIOD REQUIREMENTS (CRITICAL):",
            "- When a block TRANSITIONS into overtime, you MUST explicitly mention it",
            "- Use phrases like 'the game headed to overtime', 'forcing an extra period',",
            "  'sending the game to OT', 'requiring overtime to decide'",
            "- For NHL shootouts, mention 'heading to a shootout' or 'the shootout'",
            "- This is MANDATORY - do NOT skip mentioning overtime when it occurs",
            "",
        ])

    prompt_parts.extend([
        "Return JSON: {\"blocks\": [{\"i\": block_index, \"n\": \"narrative\"}]}",
        "",
        "BLOCKS:",
    ])

    for block in blocks:
        block_idx = block["block_index"]
        role = block["role"]
        score_before = block["score_before"]
        score_after = block["score_after"]
        key_play_ids = block["key_play_ids"]
        period_start = block.get("period_start", 1)
        period_end = block.get("period_end", period_start)

        # Detect overtime info for this block
        ot_info = detect_overtime_info(block, league_code)

        # Build period label
        period_label = _build_period_label(league_code, period_start, period_end)

        # Get key play descriptions - replace team abbreviation brackets with
        # full team names so OpenAI knows which team each play belongs to
        key_plays_desc = []
        for pid in key_play_ids:
            play = play_lookup.get(pid, {})
            desc = play.get("description", "")
            if desc:
                bracket_match = re.match(r"^\[([^\]]+)\]\s*", desc)
                if bracket_match:
                    abbrev = bracket_match.group(1).upper()
                    team_name = abbrev_to_team.get(abbrev, bracket_match.group(1))
                    clean_desc = f"({team_name}) {desc[bracket_match.end():]}"
                else:
                    clean_desc = desc
                # Strip shot distance like "26'" but not "3's" (three-pointers)
                clean_desc = re.sub(r"\b\d+'(?![a-zA-Z])\s*", "", clean_desc)
                key_plays_desc.append(f"- {clean_desc}")

        prompt_parts.append(f"\nBlock {block_idx} ({role}, {period_label}):")
        prompt_parts.append(
            f"Score: {away_team} {score_before[1]}-{score_before[0]} {home_team} "
            f"-> {away_team} {score_after[1]}-{score_after[0]} {home_team}"
        )

        # Add explicit overtime flag when block enters/contains OT
        if ot_info["enters_overtime"]:
            prompt_parts.append(f"*** ENTERS {ot_info['ot_label'].upper()} - MUST mention going to {ot_info['ot_label']} ***")
        elif ot_info["has_overtime"] and not ot_info["enters_overtime"]:
            prompt_parts.append(f"(In {ot_info['ot_label']})")

        # Flag decided games so RESOLUTION doesn't narrate garbage time
        if role == "RESOLUTION":
            final_margin = abs(score_after[0] - score_after[1])
            if final_margin >= 15:
                prompt_parts.append("(Outcome decided — summarize the final margin, skip garbage time)")

        # Lead/margin context
        lead_line = _format_lead_line(score_before, score_after, home_team, away_team)
        if lead_line:
            prompt_parts.append(lead_line)

        # Peak margin context — only when peak is meaningfully larger than boundary margin
        block_peak_margin = block.get("peak_margin", 0)
        block_peak_leader = block.get("peak_leader", 0)
        boundary_margin = max(abs(score_before[0] - score_before[1]),
                              abs(score_after[0] - score_after[1]))
        if block_peak_margin >= boundary_margin + 6:
            peak_team = home_team if block_peak_leader == 1 else away_team
            prompt_parts.append(
                f"Peak: {peak_team} led by as many as {block_peak_margin} during this stretch"
            )

        # Block star contributors
        mini_box = block.get("mini_box")
        contributors_line = _format_contributors_line(mini_box, league_code)
        if contributors_line:
            prompt_parts.append(contributors_line)

        if key_plays_desc:
            prompt_parts.append("Key plays:")
            prompt_parts.extend(key_plays_desc[:3])

    return "\n".join(prompt_parts)
