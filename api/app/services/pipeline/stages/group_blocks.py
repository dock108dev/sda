"""GROUP_BLOCKS Stage Implementation.

This stage deterministically groups validated moments into 3-7 narrative blocks.
No AI is used - block boundaries and role assignments are rule-based.

BLOCK GROUPING ALGORITHM
========================
1. Calculate target block count based on game intensity
2. Identify natural break points (lead changes, scoring runs, period boundaries)
3. Split moments into blocks using these break points
4. Assign semantic roles deterministically

BLOCK COUNT FORMULA
===================
Blowouts (is_blowout and lead_changes <= 1): return 3
Otherwise:
  base = 4
  if lead_changes >= 3: base += 1
  if lead_changes >= 6: base += 1
  if total_plays > 400: base += 1
  return min(base, 7)

ROLE ASSIGNMENT RULES
=====================
For 3-block games (blowouts):
  Block 0 -> SETUP, Block 1 -> DECISION_POINT, Block 2 -> RESOLUTION

For 4+ block games:
1. Block 0 -> SETUP (always)
2. Block N-1 -> RESOLUTION (always)
3. First lead change -> MOMENTUM_SHIFT
4. Response to lead change -> RESPONSE
5. Second-to-last block -> DECISION_POINT (if not already assigned)
6. Remaining middle blocks -> RESPONSE

CONSTRAINTS
===========
- No role appears more than twice
- SETUP always first
- RESOLUTION always last
"""

from __future__ import annotations

import logging

from ..helpers.flow_debug_logger import get_logger as get_flow_debug_logger
from ..models import StageInput, StageOutput
from .block_analysis import (
    count_lead_changes,
    detect_blowout,
    find_garbage_time_start,
    find_period_boundaries,
    find_scoring_runs,
)
from .block_types import MAX_BLOCKS, MIN_BLOCKS
from .group_helpers import calculate_block_count, compute_block_label, create_blocks
from .group_roles import assign_roles

# Import from split modules
from .group_split_points import (
    _collect_game_state_candidates,
    compress_blowout_blocks,
    find_split_points,
    find_weighted_split_points,
)
from .segment_classification import (
    classify_blocks,
    merge_blowout_compression,
)

# Map split-point trigger priority numbers (defined in group_split_points) to
# human-readable trigger names so the debug log carries readable reasons.
_PRIORITY_TRIGGER_LABELS = {
    1: "lead_change",
    2: "first_meaningful_lead",
    3: "scoring_run",
    4: "comeback_pivot",
    5: "ot_start",
    9: "period_boundary",
}


def _label_for_priority(priority: int | None) -> str:
    if priority is None:
        return "unknown"
    return _PRIORITY_TRIGGER_LABELS.get(priority, f"priority_{priority}")

logger = logging.getLogger(__name__)


async def execute_group_blocks(stage_input: StageInput) -> StageOutput:
    """Execute the GROUP_BLOCKS stage.

    Groups validated moments into 3-7 narrative blocks with semantic roles.
    This is a deterministic, rule-based stage with no AI involvement.

    Args:
        stage_input: Input containing previous_output with validated moments

    Returns:
        StageOutput with blocks data

    Raises:
        ValueError: If prerequisites not met
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting GROUP_BLOCKS for game {game_id}")

    # Get input data from previous stages
    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("GROUP_BLOCKS requires previous stage output")

    # Verify validation passed
    validated = previous_output.get("validated")
    if validated is not True:
        raise ValueError(
            f"GROUP_BLOCKS requires VALIDATE_MOMENTS to pass. Got validated={validated}"
        )

    # Get moments and PBP data
    moments = previous_output.get("moments")
    if not moments:
        raise ValueError("No moments in previous stage output")

    pbp_events = previous_output.get("pbp_events", [])

    output.add_log(f"Processing {len(moments)} moments")

    # Resolve league code early for all downstream calls
    game_context = stage_input.game_context
    league_code = game_context.get("sport", "NBA") if game_context else "NBA"

    # Archetype from CLASSIFY_GAME_SHAPE drives blowout compression refinement
    # and trigger overrides (comeback pivots, wire_to_wire first-lead, …).
    archetype = previous_output.get("archetype")

    # Calculate game metrics
    lead_changes = count_lead_changes(moments)
    total_plays = sum(len(m.get("play_ids", [])) for m in moments)
    scoring_runs = find_scoring_runs(moments, league_code=league_code)
    largest_run = max((r[2] for r in scoring_runs), default=0)

    output.add_log(f"Game metrics: {lead_changes} lead changes, {total_plays} plays")
    output.add_log(f"Found {len(scoring_runs)} scoring runs, largest: {largest_run}")
    if archetype:
        output.add_log(f"Game archetype: {archetype}")

    # Check for blowout
    is_blowout, decisive_idx, max_margin = detect_blowout(moments, league_code=league_code)
    garbage_time_idx = find_garbage_time_start(moments, league_code=league_code) if is_blowout else None

    # Treat archetype-classified blowouts the same as detect_blowout positives so
    # MLB early avalanches (which detect_blowout may miss when the lead doesn't
    # sustain across innings) still get compression.
    if not is_blowout and archetype in {"blowout", "early_avalanche_blowout"}:
        is_blowout = True
        if decisive_idx is None:
            decisive_idx = max(1, len(moments) // 3)
        if garbage_time_idx is None:
            garbage_time_idx = find_garbage_time_start(moments, league_code=league_code)

    if is_blowout:
        output.add_log(
            f"BLOWOUT DETECTED: Max margin {max_margin}, decisive at moment {decisive_idx}",
            level="warning",
        )
        if garbage_time_idx is not None:
            output.add_log(
                f"Garbage time starts at moment {garbage_time_idx}",
                level="warning",
            )

        # Use blowout compression for split points
        split_points = compress_blowout_blocks(
            moments, decisive_idx, garbage_time_idx, archetype=archetype,
        )
        target_blocks = len(split_points) + 1
        output.add_log(f"Using blowout compression: {target_blocks} blocks")
    else:
        # Calculate target block count normally
        target_blocks = calculate_block_count(
            moments, lead_changes, total_plays,
            is_blowout=is_blowout, archetype=archetype,
        )
        output.add_log(f"Target block count: {target_blocks}")

        # Find optimal split points - use drama weights if available from ANALYZE_DRAMA
        quarter_weights = previous_output.get("quarter_weights")
        if quarter_weights:
            output.add_log(f"Using drama-weighted block distribution: {quarter_weights}")
            split_points = find_weighted_split_points(
                moments, target_blocks, quarter_weights, league_code,
                archetype=archetype,
            )
        else:
            split_points = find_split_points(
                moments, target_blocks, league_code=league_code, archetype=archetype,
            )

    output.add_log(f"Split points: {split_points}")

    # Structured debug log: record boundary decisions and rejected candidates.
    # Re-derive the candidate map so each accepted boundary carries the trigger
    # priority that placed it. Period boundaries that weren't selected are
    # recorded as rejected with reason 'period_boundary_no_state_change' to
    # surface the orphan-period filter applied in find_split_points.
    debug = get_flow_debug_logger(stage_input.run_id)
    if debug is not None:
        scoring_event_count = sum(
            1 for m in moments
            if (m.get("score_after") or [0, 0]) != (m.get("score_before") or [0, 0])
        )
        debug.record_data_metrics(
            source_play_count=total_plays,
            scoring_event_count=scoring_event_count,
            lead_change_count=lead_changes,
        )
        debug.record_archetype(archetype)

        candidate_map = _collect_game_state_candidates(moments, league_code)
        period_boundary_set = set(find_period_boundaries(moments))
        for sp in split_points:
            priority = candidate_map.get(sp)
            if priority is None and sp in period_boundary_set:
                trigger = "period_boundary"
            else:
                trigger = _label_for_priority(priority)
            debug.record_boundary(moment_index=sp, trigger=trigger, priority=priority)

        for boundary in period_boundary_set:
            if boundary in split_points:
                continue
            if boundary not in candidate_map:
                debug.record_rejected_boundary(
                    moment_index=boundary,
                    reason="period_boundary_no_state_change",
                )

    # Create blocks with mini boxscores
    blocks = create_blocks(
        moments, split_points, pbp_events, game_context, league_code
    )
    output.add_log(f"Created {len(blocks)} blocks with mini boxscores")

    # Assign semantic roles
    assign_roles(blocks, league_code)

    # Log role assignments
    role_summary = {}
    for block in blocks:
        role_summary[block.role.value] = role_summary.get(block.role.value, 0) + 1
    output.add_log(f"Role assignments: {role_summary}")

    # Compute per-block narrative-job label (ISSUE-009 v2 schema field).
    # Done after roles so blowout/closeout decisions see the same archetype.
    for block in blocks:
        block.label = compute_block_label(
            block_index=block.block_index,
            block_count=len(blocks),
            score_before=block.score_before,
            score_after=block.score_after,
            archetype=archetype,
            is_blowout=is_blowout,
        )

    # v3 contract: tag every block with story_role / leverage / period_range /
    # score_context so the consumer + render prompts can see the segment beat.
    classify_blocks(
        blocks,
        league_code,
        is_blowout=is_blowout,
        garbage_time_idx=garbage_time_idx,
        decisive_moment_idx=decisive_idx,
    )

    # Collapse adjacent blowout_compression blocks. Avoids the "Inning 1 →
    # Inning 1–7 → Inning 8–9" tell where the engine emitted two structurally
    # similar middles. Re-run downstream invariants on the merged list:
    # labels, classification, and role re-assignment if the merge dropped a
    # block that was holding a unique role.
    merged_blocks = merge_blowout_compression(blocks)
    if len(merged_blocks) != len(blocks):
        output.add_log(
            f"Blowout-compression merge: {len(blocks)} → {len(merged_blocks)} blocks",
            level="warning",
        )
        blocks = merged_blocks
        # Re-assign roles in case the merge dropped a unique-role middle.
        assign_roles(blocks, league_code)
        for block in blocks:
            block.label = compute_block_label(
                block_index=block.block_index,
                block_count=len(blocks),
                score_before=block.score_before,
                score_after=block.score_after,
                archetype=archetype,
                is_blowout=is_blowout,
            )
        classify_blocks(
            blocks,
            league_code,
            is_blowout=is_blowout,
            garbage_time_idx=garbage_time_idx,
            decisive_moment_idx=decisive_idx,
        )

    # Verify block count constraints
    if len(blocks) < MIN_BLOCKS:
        output.add_log(
            f"WARNING: Only {len(blocks)} blocks created (min: {MIN_BLOCKS})",
            level="warning",
        )
    elif len(blocks) > MAX_BLOCKS:
        output.add_log(
            f"WARNING: {len(blocks)} blocks created (max: {MAX_BLOCKS})",
            level="warning",
        )

    output.add_log("GROUP_BLOCKS completed successfully")

    # Build output data
    output.data = {
        "blocks_grouped": True,
        "blocks": [b.to_dict() for b in blocks],
        "block_count": len(blocks),
        "total_moments": len(moments),
        "lead_changes": lead_changes,
        "largest_run": largest_run,
        "split_points": split_points,
        # Blowout metrics
        "is_blowout": is_blowout,
        "max_margin": max_margin,
        "decisive_moment_idx": decisive_idx,
        "garbage_time_start_idx": garbage_time_idx,
        # Drama analysis passthrough from ANALYZE_DRAMA. ``headline`` is no
        # longer emitted (deterministic stage); only weights and peak quarter
        # remain in the public passthrough.
        "quarter_weights": previous_output.get("quarter_weights"),
        "peak_quarter": previous_output.get("peak_quarter"),
        # Game-shape archetype passthrough from CLASSIFY_GAME_SHAPE so
        # downstream stages (RENDER_BLOCKS, VALIDATE_BLOCKS) keep seeing it
        # even when they read accumulated previous_output.
        "archetype": archetype,
        # Pass through from previous stages
        "moments": moments,
        "pbp_events": pbp_events,
        "validated": True,
    }

    return output
