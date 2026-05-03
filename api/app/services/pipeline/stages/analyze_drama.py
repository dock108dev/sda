"""ANALYZE_DRAMA Stage Implementation.

Deterministic per-quarter drama weighting. Consumes the archetype emitted by
CLASSIFY_GAME_SHAPE (which now runs first in the pipeline) and produces the
``quarter_weights`` map consumed by GROUP_BLOCKS via
:func:`weighted_splits.find_weighted_split_points`.

The previous version of this stage made an LLM call (gpt-4o-mini) to assign
weights. With archetype-aware boundary selection in place, a pure-Python
mapping from archetype + per-quarter signals reproduces the LLM's intent
without latency or per-game cost.

INPUT: Validated moments (passthrough) + ``archetype`` from CLASSIFY_GAME_SHAPE
OUTPUT: ``quarter_weights`` for GROUP_BLOCKS to use, plus per-quarter summary
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import StageInput, StageOutput

logger = logging.getLogger(__name__)

# Used when no quarters can be derived (e.g., empty moments). The mild Q4 bump
# preserves prior default behavior so downstream allocators see a stable shape.
DEFAULT_QUARTER_WEIGHTS = {
    "Q1": 1.0,
    "Q2": 1.0,
    "Q3": 1.0,
    "Q4": 1.5,
}

_WEIGHT_MIN = 0.5
_WEIGHT_MAX = 2.5


def _extract_quarter_summary(
    moments: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Extract compact summary data by quarter.

    Returns a dict keyed by quarter label (``Q1``..``Q4`` or ``OT1``..) with
    moment counts, score start/end, lead-change counts, peak margin/leader,
    and net point swing per quarter.
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
            }

        q = quarters[quarter_key]
        q["moment_count"] += 1
        q["score_end"] = moment.get("score_after", q["score_end"])

        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])
        margin_before = score_before[0] - score_before[1]
        margin_after = score_after[0] - score_after[1]
        if (margin_before > 0 and margin_after < 0) or (margin_before < 0 and margin_after > 0):
            q["lead_changes"] += 1

        for margin in (abs(margin_before), abs(margin_after)):
            if margin > q["peak_margin"]:
                q["peak_margin"] = margin
                raw = margin_before if abs(margin_before) == margin else margin_after
                q["peak_leader"] = 1 if raw > 0 else (-1 if raw < 0 else 0)

    for q_data in quarters.values():
        start = q_data["score_start"]
        end = q_data["score_end"]
        margin_start = start[0] - start[1]
        margin_end = end[0] - end[1]
        q_data["point_swing"] = abs(margin_end - margin_start)

    return quarters


def _quarter_drama_score(q_data: dict[str, Any]) -> float:
    """Single scalar capturing how dramatic a quarter looked.

    Higher = more dramatic. Lead changes count more than swings because a
    flip-flop quarter is the classic "deserves narrative space" signal.
    """
    return float(q_data.get("point_swing", 0)) + float(q_data.get("lead_changes", 0)) * 3.0


def compute_drama_weights(
    archetype: str | None,
    quarter_summary: dict[str, dict[str, Any]],
    league_code: str,
) -> dict[str, float]:
    """Pure deterministic drama weights derived from archetype + per-quarter signals.

    The mapping mirrors the heuristics the previous LLM prompt encoded:

    - ``wire_to_wire``           — amplify opening lead-creation period; suppress
                                   middle/late.
    - ``comeback``               — amplify the turning-point period (largest
                                   swing / lead-change cluster) heavily.
    - ``back_and_forth``         — even weights; drama is distributed.
    - ``blowout`` /
      ``early_avalanche_blowout`` — emphasize the decisive period; compress late.
    - ``low_event``              — even weights; nothing to amplify.
    - ``fake_close``             — amplify the late close-up that tightened
                                   the score.
    - ``late_separation``        — amplify the final period where separation
                                   occurred.

    Output is clamped to ``[0.5, 2.5]`` to match the ranges previously
    applied by ``find_weighted_split_points``. ``league_code`` is reserved for
    future per-sport tuning and is currently a no-op — league-specific
    amplification still happens in
    :func:`weighted_splits._apply_league_amplifiers`.
    """
    quarters = sorted(quarter_summary.keys())
    if not quarters:
        return DEFAULT_QUARTER_WEIGHTS.copy()

    weights: dict[str, float] = {q: 1.0 for q in quarters}

    if archetype == "comeback":
        turning_q = max(quarters, key=lambda q: _quarter_drama_score(quarter_summary[q]))
        weights[turning_q] = 2.2
        if "Q1" in weights and turning_q != "Q1":
            weights["Q1"] = 0.7
    elif archetype == "wire_to_wire":
        weights[quarters[0]] = 1.6
        for q in quarters[1:-1]:
            weights[q] = 0.8
        if len(quarters) > 1:
            weights[quarters[-1]] = 0.8
    elif archetype in {"blowout", "early_avalanche_blowout"}:
        weights[quarters[0]] = 1.0
        if len(quarters) > 1:
            weights[quarters[1]] = 1.4
        for q in quarters[2:]:
            weights[q] = 0.6
    elif archetype in {"back_and_forth", "low_event"}:
        for q in quarters:
            weights[q] = 1.0
    elif archetype == "fake_close":
        for q in quarters[:-1]:
            weights[q] = 0.9
        weights[quarters[-1]] = 1.8
    elif archetype == "late_separation":
        for q in quarters[:-1]:
            weights[q] = 1.0
        weights[quarters[-1]] = 1.8
    else:
        for q in quarters[:-1]:
            weights[q] = 1.0
        weights[quarters[-1]] = 1.5

    for q in weights:
        weights[q] = max(_WEIGHT_MIN, min(_WEIGHT_MAX, float(weights[q])))
    return weights


def _peak_quarter_label(quarter_weights: dict[str, float]) -> str:
    """Pick the quarter with the largest weight, breaking ties by sort order."""
    if not quarter_weights:
        return "Q4"
    return max(sorted(quarter_weights.keys()), key=lambda q: quarter_weights[q])


async def execute_analyze_drama(stage_input: StageInput) -> StageOutput:
    """Compute per-quarter drama weights deterministically.

    Reads the ``archetype`` produced by CLASSIFY_GAME_SHAPE from the
    accumulated previous-stage output and the validated moments, builds the
    per-quarter summary, and selects archetype-shaped weights via
    :func:`compute_drama_weights`.
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting ANALYZE_DRAMA for game {game_id}")

    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("ANALYZE_DRAMA requires CLASSIFY_GAME_SHAPE output")

    moments = previous_output.get("moments", [])
    pbp_events = previous_output.get("pbp_events", [])
    validated = previous_output.get("validated", False)
    archetype = previous_output.get("archetype")

    if not validated:
        raise ValueError("ANALYZE_DRAMA requires validated moments")

    league_code = (
        stage_input.game_context.get("sport", "NBA")
        if stage_input.game_context
        else "NBA"
    )

    if not moments:
        output.add_log("No moments to analyze, using default weights", level="warning")
        output.data = {
            "drama_analyzed": False,
            "quarter_weights": DEFAULT_QUARTER_WEIGHTS.copy(),
            "peak_quarter": "Q4",
            "quarter_summary": {},
            "moments": moments,
            "pbp_events": pbp_events,
            "validated": validated,
            "archetype": archetype,
            "errors": previous_output.get("errors", []),
        }
        return output

    quarter_summary = _extract_quarter_summary(moments)
    output.add_log(
        f"Extracted summary for {len(quarter_summary)} quarters; archetype={archetype}"
    )

    quarter_weights = compute_drama_weights(archetype, quarter_summary, league_code)
    peak_quarter = _peak_quarter_label(quarter_weights)

    output.add_log(f"Drama weights: {quarter_weights} (peak={peak_quarter})")

    output.data = {
        "drama_analyzed": True,
        "quarter_weights": quarter_weights,
        "peak_quarter": peak_quarter,
        "quarter_summary": quarter_summary,
        "moments": moments,
        "pbp_events": pbp_events,
        "validated": validated,
        "archetype": archetype,
        "errors": previous_output.get("errors", []),
    }

    output.add_log("ANALYZE_DRAMA complete")
    return output
