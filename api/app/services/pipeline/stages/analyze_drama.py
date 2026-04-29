"""ANALYZE_DRAMA Stage Implementation.

This stage uses AI to identify the dramatic peak of a game and assign
weights to each quarter/period for block distribution.

The goal is to allocate more narrative blocks to the exciting parts of the
game (comebacks, close finishes, clutch moments) rather than distributing
blocks evenly across all quarters.

INPUT: Validated moments with scores and periods
OUTPUT: Quarter weights that GROUP_BLOCKS uses for block distribution

TOKEN EFFICIENCY
================
Input to OpenAI: ~200-400 tokens (compact game summary)
Output from OpenAI: ~100-150 tokens (quarter weights + headline)
Total: ~400-550 tokens per game = fraction of a cent
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ...openai_client import get_openai_client
from ..models import StageInput, StageOutput

logger = logging.getLogger(__name__)

# Default weights if AI fails or is unavailable
DEFAULT_QUARTER_WEIGHTS = {
    "Q1": 1.0,
    "Q2": 1.0,
    "Q3": 1.0,
    "Q4": 1.5,  # Slight bias toward end of game
}


def _extract_quarter_summary(
    moments: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Extract compact summary data by quarter.

    Returns dict with structure:
    {
        "Q1": {
            "moment_count": 8,
            "score_start": [0, 0],
            "score_end": [23, 30],
            "point_swing": 7,  # Net change in margin
            "lead_changes": 2,
        },
        ...
    }
    """
    quarters: dict[str, dict[str, Any]] = {}

    for moment in moments:
        period = moment.get("period", 1)
        quarter_key = f"Q{period}" if period <= 4 else f"OT{period - 4}"

        if quarter_key not in quarters:
            quarters[quarter_key] = {
                "moment_count": 0,
                "score_start": moment.get("score_before", [0, 0]),
                "score_end": moment.get("score_after", [0, 0]),
                "lead_changes": 0,
                "peak_margin": 0,
                "peak_leader": 0,
                "moments": [],
            }

        q = quarters[quarter_key]
        q["moment_count"] += 1
        q["score_end"] = moment.get("score_after", q["score_end"])
        q["moments"].append(moment)

        # Count lead changes within quarter
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])
        margin_before = score_before[0] - score_before[1]
        margin_after = score_after[0] - score_after[1]
        if (margin_before > 0 and margin_after < 0) or (margin_before < 0 and margin_after > 0):
            q["lead_changes"] += 1

        # Track peak margin within the quarter
        for margin in (abs(margin_before), abs(margin_after)):
            if margin > q["peak_margin"]:
                q["peak_margin"] = margin
                # Use the margin that set the peak to determine leader
                raw = margin_before if abs(margin_before) == margin else margin_after
                q["peak_leader"] = 1 if raw > 0 else (-1 if raw < 0 else 0)

    # Calculate point swings
    for q_data in quarters.values():
        start = q_data["score_start"]
        end = q_data["score_end"]
        margin_start = start[0] - start[1]
        margin_end = end[0] - end[1]
        q_data["point_swing"] = abs(margin_end - margin_start)
        # Remove moments list to keep summary compact
        del q_data["moments"]

    return quarters


def _build_drama_prompt(
    quarter_summary: dict[str, dict[str, Any]],
    game_context: dict[str, str],
    final_score: list[int],
) -> str:
    """Build compact prompt for drama analysis.

    Keeps token count low by sending only essential game data.
    """
    home_team = game_context.get("home_team", "Home")
    away_team = game_context.get("away_team", "Away")
    sport = game_context.get("sport", "basketball")

    # Build compact quarter data
    quarter_lines = []
    for q_key in sorted(quarter_summary.keys()):
        q = quarter_summary[q_key]
        end_margin = abs(q["score_end"][0] - q["score_end"][1])
        peak = q.get("peak_margin", 0)
        peak_suffix = ""
        if peak >= end_margin + 6:
            peak_suffix = f", peak margin {peak}"
        quarter_lines.append(
            f"{q_key}: {q['score_start'][0]}-{q['score_start'][1]} → "
            f"{q['score_end'][0]}-{q['score_end'][1]} "
            f"({q['moment_count']} moments, {q['lead_changes']} lead changes, "
            f"{q['point_swing']}pt swing{peak_suffix})"
        )

    final_margin = abs(final_score[0] - final_score[1])
    winner = home_team if final_score[0] > final_score[1] else away_team

    prompt = f"""Analyze this {sport} game to identify where the drama/excitement peaked.

Game: {away_team} @ {home_team}
Final: {final_score[0]}-{final_score[1]} ({winner} wins by {final_margin})

Score progression by quarter:
{chr(10).join(quarter_lines)}

Based on this data, assign a weight (0.5 to 2.5) to each quarter indicating how much of the narrative should focus on that quarter. Higher weight = more exciting/dramatic = deserves more coverage.

Consider:
- Close games deserve more Q4 weight
- Big comebacks deserve weight on the comeback quarters
- Blowouts should compress the boring stretches
- Lead changes and point swings indicate drama
- Peak margins much larger than final margins indicate comebacks worth narrating

Respond with ONLY valid JSON:
{{"quarter_weights": {{"Q1": 1.0, "Q2": 1.0, "Q3": 1.5, "Q4": 2.0}}, "peak_quarter": "Q3", "story_type": "comeback", "headline": "Brief 5-10 word summary"}}"""

    return prompt


def _parse_ai_response(response_text: str) -> dict[str, Any]:
    """Parse AI response. Fails on malformed JSON."""
    # Extract JSON from response
    text = response_text.strip()

    # Handle markdown code blocks
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    return json.loads(text)


async def execute_analyze_drama(stage_input: StageInput) -> StageOutput:
    """Analyze game drama and compute quarter weights for block distribution.

    This stage:
    1. Extracts compact game summary from validated moments
    2. Calls OpenAI to identify dramatic peaks
    3. Returns quarter weights for GROUP_BLOCKS to use

    Args:
        stage_input: Input containing validated moments from VALIDATE_MOMENTS

    Returns:
        StageOutput with quarter_weights and drama analysis

    Raises:
        ValueError: If prerequisites not met
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting ANALYZE_DRAMA for game {game_id}")

    # Get previous stage output
    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("ANALYZE_DRAMA requires VALIDATE_MOMENTS output")

    moments = previous_output.get("moments", [])
    pbp_events = previous_output.get("pbp_events", [])
    validated = previous_output.get("validated", False)

    if not validated:
        raise ValueError("ANALYZE_DRAMA requires validated moments")

    if not moments:
        output.add_log("No moments to analyze, using default weights", level="warning")
        output.data = {
            "drama_analyzed": False,
            "quarter_weights": DEFAULT_QUARTER_WEIGHTS.copy(),
            "peak_quarter": "Q4",
            "story_type": "standard",
            "headline": "",
            "moments": moments,
            "pbp_events": pbp_events,
            "validated": validated,
            "errors": previous_output.get("errors", []),
        }
        return output

    # Extract quarter summary
    quarter_summary = _extract_quarter_summary(moments)
    output.add_log(f"Extracted summary for {len(quarter_summary)} quarters")

    # Get final score from last moment
    last_moment = moments[-1]
    final_score = last_moment.get("score_after", [0, 0])

    # Get OpenAI client
    openai_client = get_openai_client()

    if openai_client is None:
        output.add_log("OpenAI not configured, using default weights", level="warning")
        drama_result = {
            "quarter_weights": DEFAULT_QUARTER_WEIGHTS.copy(),
            "peak_quarter": "Q4",
            "story_type": "standard",
            "headline": "",
        }
    else:
        # Build and send prompt
        prompt = _build_drama_prompt(
            quarter_summary,
            stage_input.game_context,
            final_score,
        )

        output.add_log(f"Calling OpenAI for drama analysis (~{len(prompt.split())} words)")

        response_text = await asyncio.to_thread(
            openai_client.generate,
            prompt=prompt,
            temperature=0.3,  # Low temp for consistency
            max_tokens=200,  # Response is compact JSON
        )

        drama_result = _parse_ai_response(response_text)
        output.add_log(
            f"Drama analysis: peak={drama_result.get('peak_quarter')}, "
            f"type={drama_result.get('story_type')}"
        )

    # Validate and normalize weights
    quarter_weights = drama_result.get("quarter_weights", DEFAULT_QUARTER_WEIGHTS)

    # Ensure all quarters in the game have weights
    for q_key in quarter_summary:
        if q_key not in quarter_weights:
            quarter_weights[q_key] = 1.0

    # Clamp weights to valid range
    for q_key in quarter_weights:
        quarter_weights[q_key] = max(0.5, min(2.5, float(quarter_weights[q_key])))

    output.add_log(f"Final quarter weights: {quarter_weights}")

    # Build output with all passthrough data
    output.data = {
        "drama_analyzed": True,
        "quarter_weights": quarter_weights,
        "peak_quarter": drama_result.get("peak_quarter", "Q4"),
        "story_type": drama_result.get("story_type", "standard"),
        "headline": drama_result.get("headline", ""),
        "quarter_summary": quarter_summary,
        # Passthrough from previous stage
        "moments": moments,
        "pbp_events": pbp_events,
        "validated": validated,
        "errors": previous_output.get("errors", []),
    }

    output.add_log("ANALYZE_DRAMA complete")
    return output
