"""GENERATE_MOMENTS Stage Implementation.

This stage segments normalized PBP data into condensed moments using
deterministic, rule-based boundary detection, and selects which plays
must be explicitly narrated.

FLOW CONTRACT ALIGNMENT
=======================
This implementation adheres to the game flow contract:
- Moments are derived DIRECTLY from PBP data
- No signals, momentum, or narrative abstractions
- No LLM/OpenAI calls
- Ordering is by play_index (canonical)
- Output contains NO narrative text

SEGMENTATION RULES
==================
The system uses SOFT caps that prefer but don't force closure:

SOFT CAP: SOFT_CAP_PLAYS = 8 plays
- Prefer closing when reached
- Allow continuation if game flow is continuous

ABSOLUTE CAP: ABSOLUTE_MAX_PLAYS = 12 plays
- Hard limit, must close (safety valve)

HARD BREAK CONDITIONS (always close):
1. Period boundary (end/start of quarter)
2. Lead change
3. Would create >2 explicitly narrated plays
4. ABSOLUTE_MAX_PLAYS reached

SOFT BREAK CONDITIONS (prefer closing):
1. SOFT_CAP_PLAYS reached
2. Scoring play (but not lead change)
3. Turnover/possession change
4. Stoppage (timeout/review)
5. Second explicitly narrated play encountered

MERGE ELIGIBILITY (encourage continuing):
- Small moments (< MIN_PLAYS_BEFORE_SOFT_CLOSE) always merge
- Larger moments merge if no scoring has occurred
- Game flow is continuous (same period)

TARGET DISTRIBUTION:
- ~80% of moments <= 8 plays
- ~80% of moments with <= 1 explicitly narrated play
- ~25-40% reduction in moment count

EXPLICIT NARRATION SELECTION
============================
Each moment must identify at least one play for explicit narration.
Selection rules (in priority order):
1. Scoring plays: Any play where score changed from previous play
2. Notable plays: Plays with notable play_types (blocks, steals, etc.)
3. Fallback: Last play in the moment

Constraint: Maximum 2 explicitly narrated plays per moment.

GUARANTEES
==========
1. Full play coverage: Every play appears in exactly one moment
2. No overlap: No play_id appears in more than one moment
3. Correct ordering: Moments ordered by first play's play_index
4. Non-empty: Every moment has at least 1 play_id
5. Narration coverage: Every moment has at least 1 explicitly_narrated_play_id
6. Narration subset: explicitly_narrated_play_ids is a subset of play_ids
7. No cross-period moments: All plays in a moment are from the same period
8. Max narration: No moment has more than 2 explicitly_narrated_play_ids
"""

from __future__ import annotations

import logging
from typing import Any

from ..helpers.score_timeline import find_first_lead_created_play_idx
from ..models import StageInput, StageOutput
from .boundary_detection import (
    is_merge_eligible,
    should_force_close_moment,
    should_prefer_close_moment,
)
from .explicit_selection import select_explicitly_narrated_plays

# Import from modular helpers
from .moment_types import (
    MAX_EXPLICIT_PLAYS_PER_MOMENT,
    SOFT_CAP_PLAYS,
    BoundaryReason,
    CompressionMetrics,
)
from .play_classification import is_period_boundary
from .score_detection import get_score_after_moment, get_score_before_moment

logger = logging.getLogger(__name__)


def _finalize_moment(
    all_events: list[dict[str, Any]],
    moment_plays: list[dict[str, Any]],
    moment_start_idx: int,
) -> dict[str, Any]:
    """Finalize a moment with all required metadata.

    Args:
        all_events: All PBP events (for score_before lookup)
        moment_plays: Plays in this moment
        moment_start_idx: Index of first play in all_events

    Returns:
        Moment dict matching required output shape
    """
    first_play = moment_plays[0]
    last_play = moment_plays[-1]

    # Extract play_ids in order
    play_ids = [p["play_index"] for p in moment_plays]

    # Select plays that must be explicitly narrated
    explicitly_narrated_play_ids = select_explicitly_narrated_plays(
        moment_plays, all_events, moment_start_idx
    )

    # Period from first play
    period = first_play.get("quarter") or 1

    # Clock values (may be null)
    start_clock = first_play.get("game_clock")
    end_clock = last_play.get("game_clock")

    # Score states
    score_before = list(get_score_before_moment(all_events, moment_start_idx))
    score_after = list(get_score_after_moment(last_play))

    return {
        "play_ids": play_ids,
        "explicitly_narrated_play_ids": explicitly_narrated_play_ids,
        "period": period,
        "start_clock": start_clock,
        "end_clock": end_clock,
        "score_before": score_before,
        "score_after": score_after,
    }


def _segment_plays_into_moments(
    events: list[dict[str, Any]],
    league_code: str = "NBA",
) -> tuple[list[dict[str, Any]], CompressionMetrics]:
    """Segment PBP events into condensed moments using soft-capped compression.

    ALGORITHM:
    1. Iterate through events in play_index order (already sorted)
    2. Accumulate plays into current moment
    3. Check HARD boundary conditions (must close)
    4. Check SOFT boundary conditions (prefer close)
    5. Check merge eligibility (can override soft conditions)
    6. Close moment when appropriate

    HARD BOUNDARIES (always close):
    - Period change (start new moment BEFORE the play)
    - Lead change
    - >2 explicitly narrated plays would result
    - ABSOLUTE_MAX_PLAYS reached

    SOFT BOUNDARIES (prefer closing):
    - SOFT_CAP_PLAYS reached
    - Scoring play
    - Stoppage play
    - Turnover
    - Second explicit play

    MERGE ELIGIBILITY (can override soft):
    - No scoring in current moment
    - Continuous game flow

    Args:
        events: Normalized PBP events, ordered by play_index

    Returns:
        Tuple of (moments list, compression metrics)

    Raises:
        ValueError: If any guarantee is violated
    """
    if not events:
        return [], CompressionMetrics()

    # Pre-compute the play_index that first creates a meaningful lead so the
    # HARD boundary trigger can fire exactly once per game rather than scanning
    # the full event list on every call.
    first_meaningful_lead_play_idx = find_first_lead_created_play_idx(
        events, league_code=league_code
    )

    moments: list[dict[str, Any]] = []
    current_moment_plays: list[dict[str, Any]] = []
    current_moment_start_idx = 0
    metrics = CompressionMetrics(total_plays=len(events))

    # Track all play_ids for coverage verification
    all_play_ids: set[int] = set()
    assigned_play_ids: set[int] = set()

    def finalize_current_moment(reason: BoundaryReason) -> None:
        """Helper to finalize and record the current moment."""
        nonlocal current_moment_plays, current_moment_start_idx

        if not current_moment_plays:
            return

        moment = _finalize_moment(events, current_moment_plays, current_moment_start_idx)
        moments.append(moment)

        # Track metrics
        play_count = len(moment["play_ids"])
        explicit_count = len(moment["explicitly_narrated_play_ids"])
        metrics.plays_per_moment.append(play_count)
        metrics.explicit_plays_per_moment.append(explicit_count)
        metrics.boundary_reasons[reason.value] = (
            metrics.boundary_reasons.get(reason.value, 0) + 1
        )

        for p in current_moment_plays:
            assigned_play_ids.add(p["play_index"])

        current_moment_plays = []

    for i, event in enumerate(events):
        play_index = event.get("play_index")
        if play_index is None:
            raise ValueError(f"Event at position {i} missing play_index")

        all_play_ids.add(play_index)

        previous_event = events[i - 1] if i > 0 else None
        next_event = events[i + 1] if i + 1 < len(events) else None

        # HARD: Period boundary - close current and start new moment BEFORE this play
        if previous_event and is_period_boundary(event, previous_event):
            if current_moment_plays:
                finalize_current_moment(BoundaryReason.PERIOD_BOUNDARY)
            current_moment_start_idx = i

        # Add current play to moment
        current_moment_plays.append(event)

        # Last play always ends moment
        if i == len(events) - 1:
            finalize_current_moment(BoundaryReason.END_OF_INPUT)
            continue

        # Check HARD boundary conditions (must close)
        should_close_hard, hard_reason = should_force_close_moment(
            current_moment_plays,
            event,
            previous_event,
            events,
            current_moment_start_idx,
            first_meaningful_lead_play_idx=first_meaningful_lead_play_idx,
        )
        if should_close_hard and hard_reason:
            finalize_current_moment(hard_reason)
            current_moment_start_idx = i + 1
            continue

        # Check SOFT boundary conditions (prefer close)
        should_close_soft, soft_reason = should_prefer_close_moment(
            current_moment_plays,
            event,
            previous_event,
            events,
            current_moment_start_idx,
        )

        if should_close_soft and soft_reason:
            # Check if merge eligibility overrides the soft condition
            merge_eligible = is_merge_eligible(
                current_moment_plays,
                event,
                previous_event,
                next_event,
            )

            # Only override soft conditions if:
            # 1. Merge is eligible (checks moment size and game flow)
            # 2. We haven't hit soft cap yet
            # 3. The soft reason isn't the cap itself
            # Note: SCORING_PLAY can be overridden to allow grouping
            # of back-to-back scores into coherent moments
            should_override = (
                merge_eligible
                and len(current_moment_plays) < SOFT_CAP_PLAYS
                and soft_reason not in {
                    BoundaryReason.SOFT_CAP_REACHED,  # Don't override cap
                }
            )

            if not should_override:
                finalize_current_moment(soft_reason)
                current_moment_start_idx = i + 1

    # Ensure all plays are assigned
    if current_moment_plays:
        finalize_current_moment(BoundaryReason.END_OF_INPUT)

    # Update metrics
    metrics.total_moments = len(moments)

    # VERIFICATION: Full coverage
    if all_play_ids != assigned_play_ids:
        missing = all_play_ids - assigned_play_ids
        extra = assigned_play_ids - all_play_ids
        raise ValueError(
            f"Play coverage violation. Missing: {missing}, Extra: {extra}"
        )

    # VERIFICATION: Non-empty moments and narration
    for idx, moment in enumerate(moments):
        if not moment["play_ids"]:
            raise ValueError(f"Moment {idx} has no play_ids")

        if not moment.get("explicitly_narrated_play_ids"):
            raise ValueError(f"Moment {idx} has no explicitly_narrated_play_ids")

        # VERIFICATION: Narrated plays are subset of play_ids
        play_ids_set = set(moment["play_ids"])
        narrated_set = set(moment["explicitly_narrated_play_ids"])
        if not narrated_set.issubset(play_ids_set):
            invalid = narrated_set - play_ids_set
            raise ValueError(
                f"Moment {idx} has narrated play_ids not in play_ids: {invalid}"
            )

        # VERIFICATION: Max narration constraint
        if len(narrated_set) > MAX_EXPLICIT_PLAYS_PER_MOMENT:
            raise ValueError(
                f"Moment {idx} has {len(narrated_set)} narrated plays, "
                f"exceeds max of {MAX_EXPLICIT_PLAYS_PER_MOMENT}"
            )

    # VERIFICATION: Correct ordering
    prev_first_play = -1
    for idx, moment in enumerate(moments):
        first_play = moment["play_ids"][0]
        if first_play <= prev_first_play:
            raise ValueError(
                f"Moment ordering violation at index {idx}: "
                f"first_play {first_play} <= previous {prev_first_play}"
            )
        prev_first_play = first_play

    # Note: Cross-period moments are prevented by period boundary being a HARD break
    # during moment generation, so no post-hoc verification is needed.

    return moments, metrics


async def execute_generate_moments(stage_input: StageInput) -> StageOutput:
    """Execute the GENERATE_MOMENTS stage.

    Reads normalized PBP from previous stage output and segments
    plays into condensed moments using soft-capped compression rules.

    NO NARRATIVE TEXT IS GENERATED.
    NO LLM/OPENAI CALLS ARE MADE.

    Soft-capped moment compression targets:
    - Target: ~80% of moments <= 8 plays
    - Target: ~80% of moments with <= 1 explicit play
    - Target: ~25-40% reduction in moment count

    Args:
        stage_input: Input containing previous_output with pbp_events

    Returns:
        StageOutput with moments list and compression metrics

    Raises:
        ValueError: If input is invalid or guarantees are violated
    """
    output = StageOutput(data={})
    game_id = stage_input.game_id

    output.add_log(f"Starting GENERATE_MOMENTS for game {game_id}")

    # Get normalized PBP from previous stage output
    previous_output = stage_input.previous_output
    if not previous_output:
        raise ValueError("GENERATE_MOMENTS requires previous stage output")

    pbp_events = previous_output.get("pbp_events")
    if not pbp_events:
        raise ValueError("No pbp_events in previous stage output")

    output.add_log(f"Processing {len(pbp_events)} PBP events")

    # Verify events are ordered by play_index
    prev_index = -1
    for i, event in enumerate(pbp_events):
        play_index = event.get("play_index")
        if play_index is None:
            raise ValueError(f"Event at position {i} missing play_index")
        if play_index <= prev_index:
            raise ValueError(
                f"Events not ordered by play_index at position {i}: "
                f"{play_index} <= {prev_index}"
            )
        prev_index = play_index

    output.add_log("Verified play_index ordering")

    # Resolve league code for boundary detection (drives the moment-level
    # FIRST_MEANINGFUL_LEAD HARD trigger threshold).
    game_context = stage_input.game_context
    league_code = game_context.get("sport", "NBA") if game_context else "NBA"

    # Segment plays into moments with soft-capped compression
    moments, metrics = _segment_plays_into_moments(pbp_events, league_code=league_code)

    output.add_log(f"Segmented into {len(moments)} moments")

    # Log compression metrics
    output.add_log(
        f"Compression metrics: "
        f"{metrics.pct_moments_under_soft_cap:.1f}% <= {SOFT_CAP_PLAYS} plays, "
        f"{metrics.pct_moments_single_explicit:.1f}% with <= 1 explicit play"
    )
    output.add_log(
        f"Moment sizes: median={metrics.median_plays_per_moment:.1f}, "
        f"max={metrics.max_plays_observed}"
    )

    # Log moment size distribution for reviewability
    sizes = [len(m["play_ids"]) for m in moments]
    if sizes:
        avg_size = sum(sizes) / len(sizes)
        min_size = min(sizes)
        max_size = max(sizes)
        output.add_log(
            f"Moment sizes: min={min_size}, max={max_size}, avg={avg_size:.1f}"
        )

    # Count scoring moments for verification
    scoring_moments = sum(
        1 for m in moments if m["score_before"] != m["score_after"]
    )
    output.add_log(f"Scoring moments: {scoring_moments}")

    # Log explicitly narrated play statistics
    narrated_counts = [len(m["explicitly_narrated_play_ids"]) for m in moments]
    total_narrated = sum(narrated_counts)
    total_plays = sum(sizes)
    narration_pct = (total_narrated / total_plays * 100) if total_plays > 0 else 0
    output.add_log(
        f"Narrated plays: {total_narrated}/{total_plays} ({narration_pct:.1f}%)"
    )
    if narrated_counts:
        output.add_log(
            f"Narrated per moment: min={min(narrated_counts)}, max={max(narrated_counts)}, "
            f"avg={sum(narrated_counts)/len(narrated_counts):.1f}"
        )

    # Log boundary reason distribution
    if metrics.boundary_reasons:
        reason_summary = ", ".join(
            f"{k}={v}" for k, v in sorted(metrics.boundary_reasons.items())
        )
        output.add_log(f"Boundary reasons: {reason_summary}")

    # Warn if distribution targets are not met
    if metrics.pct_moments_under_soft_cap < 80:
        output.add_log(
            f"WARNING: Only {metrics.pct_moments_under_soft_cap:.1f}% of moments "
            f"have <= {SOFT_CAP_PLAYS} plays (target: 80%)",
            level="warning",
        )
    if metrics.pct_moments_single_explicit < 80:
        output.add_log(
            f"WARNING: Only {metrics.pct_moments_single_explicit:.1f}% of moments "
            f"have <= 1 explicit play (target: 80%)",
            level="warning",
        )

    # Output includes moments and compression metrics for monitoring
    output.data = {
        "moments": moments,
        # Compression metrics for monitoring and validation
        "compression_metrics": metrics.to_dict(),
    }

    output.add_log("GENERATE_MOMENTS completed successfully")

    return output
