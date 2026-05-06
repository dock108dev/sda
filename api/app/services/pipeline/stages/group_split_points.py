"""Split point algorithms for GROUP_BLOCKS stage.

Game-state-driven block boundaries. Candidate moments are scored by trigger
priority (lead change > first meaningful lead > scoring run > game out of reach
> comeback flip > OT start), and period boundaries are demoted: a period
boundary that does not coincide with another game-state trigger is dropped
from the candidate set.

The drama-weighted distribution lives in :mod:`weighted_splits`; this module
runs the same trigger-derivation + period-orphan filter against the weighted
output so both code paths satisfy the boundary contract.
"""

from __future__ import annotations

import logging
from typing import Any

from .block_analysis import (
    find_comeback_pivot_moments,
    find_first_meaningful_lead_moment,
    find_first_scoring_moment,
    find_lead_change_indices,
    find_multi_goal_period_end_indices,
    find_overtime_start_moment,
    find_period_boundaries,
    find_scoring_runs,
    find_tied_state_flip_indices,
)
from .block_types import MIN_BLOCKS
from .league_config import LEAGUE_CONFIG
from .weighted_splits import find_weighted_split_points as _weighted_split_points_inner

# Blowout games get fewer blocks (less narrative needed)
BLOWOUT_MAX_BLOCKS = 5

# Period boundary candidates are kept only when a game-state trigger lands
# within this many moments — otherwise the boundary is "orphan" and dropped.
_PERIOD_COINCIDE_WINDOW = 1

# Trigger priorities: lower number = higher priority. Period boundary is the
# lowest priority and is also gated by the orphan filter.
_PRIORITY_LEAD_CHANGE = 1
_PRIORITY_FIRST_LEAD = 2
_PRIORITY_SCORING_RUN = 3
_PRIORITY_COMEBACK = 4
_PRIORITY_OT_START = 5
_PRIORITY_PERIOD = 9

# Archetypes for which we cap the number of blocks aggressively. low_event
# games per the spec produce 3 or fewer block boundaries (i.e. ≤4 blocks).
_LOW_EVENT_MAX_BOUNDARIES = 3

logger = logging.getLogger(__name__)


def compress_blowout_blocks(
    moments: list[dict[str, Any]],
    decisive_idx: int,
    garbage_time_idx: int | None,
    archetype: str | None = None,
) -> list[int]:
    """Generate split points for blowout games.

    Blowout compression strategy:
    - 1-2 blocks before decisive moment (the interesting part)
    - 1 block for the decisive stretch
    - 1 block for everything after (compressed)

    Args:
        moments: List of validated moments
        decisive_idx: Index where game became decisive
        garbage_time_idx: Index where garbage time starts (if any)
        archetype: Optional archetype string. ``early_avalanche_blowout``
            (MLB) tightens the SETUP block since the avalanche happens in the
            opening innings — ``late_separation`` and bare ``blowout`` keep
            the original SETUP cadence.

    Returns:
        List of split point indices
    """
    n = len(moments)
    split_points: list[int] = []

    # Ensure we have at least MIN_BLOCKS
    # For blowout: [SETUP][MOMENTUM_SHIFT][RESPONSE or compress][RESOLUTION]

    if decisive_idx is None:
        decisive_idx = n // 3  # Default to 1/3 mark

    # First split: After SETUP (first ~15-20% of moments, but before decisive).
    # For early_avalanche_blowout, the avalanche IS the setup — clip the SETUP
    # block tighter so the decisive stretch starts sooner.
    setup_divisor = 8 if archetype == "early_avalanche_blowout" else 6
    setup_end = min(max(1, n // setup_divisor), decisive_idx - 1)
    if setup_end > 0:
        split_points.append(setup_end)

    # Second split: The decisive moment (where blowout began)
    if decisive_idx > setup_end:
        split_points.append(decisive_idx)

    # Third split: If garbage time exists, compress everything after
    if garbage_time_idx is not None and garbage_time_idx > decisive_idx:
        # Put garbage time in its own minimal block
        split_points.append(garbage_time_idx)
    else:
        # If no garbage time, split remaining ~evenly
        remaining_start = max(split_points) if split_points else 0
        remaining = n - remaining_start
        if remaining > n // 3:
            # Add one more split for DECISION_POINT
            mid_remaining = remaining_start + remaining // 2
            if mid_remaining not in split_points and mid_remaining > remaining_start:
                split_points.append(mid_remaining)

    # Ensure unique and sorted
    split_points = sorted(set(sp for sp in split_points if 0 < sp < n))

    # Ensure we have at least MIN_BLOCKS - 1 split points
    while len(split_points) < MIN_BLOCKS - 1:
        # Add evenly distributed splits between existing points
        for i in range(len(split_points) - 1):
            gap = split_points[i + 1] - split_points[i]
            if gap > 2:
                new_split = split_points[i] + gap // 2
                if new_split not in split_points:
                    split_points.append(new_split)
                    break
        else:
            # Add at end if needed
            if split_points and split_points[-1] < n - 2:
                split_points.append(split_points[-1] + (n - split_points[-1]) // 2)
            else:
                break
        split_points = sorted(set(split_points))

    return split_points[:BLOWOUT_MAX_BLOCKS - 1]  # Cap at blowout max


def _collect_game_state_candidates(
    moments: list[dict[str, Any]],
    league_code: str,
) -> dict[int, int]:
    """Build the candidate split-point map keyed by moment index.

    Each key maps to the highest-priority (lowest number) trigger reason that
    fired at that moment. Period boundaries are *not* included here — they're
    layered on top in :func:`_apply_period_boundaries` so the orphan filter
    can examine the game-state set first.
    """
    n = len(moments)
    candidates: dict[int, int] = {}

    def add(idx: int, priority: int) -> None:
        if 0 < idx < n:
            existing = candidates.get(idx)
            if existing is None or priority < existing:
                candidates[idx] = priority

    for idx in find_lead_change_indices(moments):
        add(idx, _PRIORITY_LEAD_CHANGE)

    flmi = find_first_meaningful_lead_moment(moments, league_code=league_code)
    if flmi is not None:
        add(flmi, _PRIORITY_FIRST_LEAD)

    # Pull league-specific scoring-run minimum from LEAGUE_CONFIG so MLB
    # multi-run innings (3+) and NBA 8-0 runs are both detected.
    code = (league_code or "").upper()
    cfg = LEAGUE_CONFIG.get(code, LEAGUE_CONFIG["NBA"])
    min_run = int(cfg.get("scoring_run_min", 8))
    for start, end, _ in find_scoring_runs(
        moments, min_run_size=min_run, league_code=league_code,
    ):
        add(start, _PRIORITY_SCORING_RUN)
        add(end + 1, _PRIORITY_SCORING_RUN)

    deficit_peak, tie_idx = find_comeback_pivot_moments(moments, league_code=league_code)
    if deficit_peak is not None:
        add(deficit_peak, _PRIORITY_COMEBACK)
    if tie_idx is not None:
        add(tie_idx, _PRIORITY_COMEBACK)

    if (league_code or "").upper() == "NHL":
        ot_idx = find_overtime_start_moment(moments, league_code=league_code)
        if ot_idx is not None:
            add(ot_idx, _PRIORITY_OT_START)

        # NHL goal-sequence triggers: the first goal opens the narrative; tied
        # flips (tying / go-ahead-from-tie goals) are the dominant boundary
        # signal in low-scoring sport. Multi-goal periods get a period-end
        # boundary even without a coincident lead trigger.
        first_goal_idx = find_first_scoring_moment(moments)
        if first_goal_idx is not None:
            add(first_goal_idx, _PRIORITY_FIRST_LEAD)

        for tied_idx in find_tied_state_flip_indices(moments):
            add(tied_idx, _PRIORITY_LEAD_CHANGE)

        for mg_idx in find_multi_goal_period_end_indices(moments):
            add(mg_idx, _PRIORITY_SCORING_RUN)

    return candidates


def _apply_period_boundaries(
    candidates: dict[int, int],
    moments: list[dict[str, Any]],
) -> None:
    """Layer period boundaries onto the candidate map under the orphan rule.

    A period boundary becomes a candidate split point only when at least one
    game-state trigger lies within ``_PERIOD_COINCIDE_WINDOW`` moments of it.
    This enforces AC #2: "Period/inning end alone does not produce a block
    boundary — it must coincide with a game-state change." Mutates the dict
    in place to keep the call sites readable.
    """
    n = len(moments)
    if not candidates:
        return
    state_indices = list(candidates.keys())
    for idx in find_period_boundaries(moments):
        if not (0 < idx < n):
            continue
        if any(abs(idx - other) <= _PERIOD_COINCIDE_WINDOW for other in state_indices):
            existing = candidates.get(idx)
            if existing is None or existing > _PRIORITY_PERIOD:
                candidates[idx] = _PRIORITY_PERIOD


def _filter_orphan_period_boundaries(
    split_points: list[int],
    moments: list[dict[str, Any]],
    state_change_indices: set[int],
) -> list[int]:
    """Drop split points that sit on a period boundary without a coincident trigger.

    Used by both :func:`find_split_points` and :func:`find_weighted_split_points`
    so the AC#2 contract holds across both algorithms.
    """
    if not split_points:
        return split_points
    period_boundary_set = set(find_period_boundaries(moments))
    if not period_boundary_set:
        return split_points
    filtered: list[int] = []
    for sp in split_points:
        if sp in period_boundary_set:
            coincides = any(
                abs(sp - state_idx) <= _PERIOD_COINCIDE_WINDOW
                for state_idx in state_change_indices
            )
            if not coincides:
                continue
        filtered.append(sp)
    return filtered


def _enforce_archetype_required_splits(
    selected: list[int],
    candidates: dict[int, int],
    moments: list[dict[str, Any]],
    league_code: str,
    archetype: str | None,
    needed_splits: int,
) -> list[int]:
    """Ensure archetype-mandated split points are present.

    For archetypes whose narrative arc relies on specific pivots — comeback's
    deficit peak + tie/flip, wire-to-wire's first lead, late_separation's
    separation moment — surface those moments into ``selected`` even if the
    generic priority sort would have skipped them in favor of nearer-priority
    candidates. NHL OT/SO start is also enforced here because the dedicated-
    OT-block contract is league-level, not archetype-level.
    """
    n = len(moments)
    required: list[int] = []

    if (league_code or "").upper() == "NHL":
        ot_idx = find_overtime_start_moment(moments, league_code=league_code)
        if ot_idx is not None and 0 < ot_idx < n:
            required.append(ot_idx)

    if not archetype and not required:
        return selected

    if archetype == "comeback":
        deficit_peak, tie_idx = find_comeback_pivot_moments(moments, league_code=league_code)
        if deficit_peak is not None and 0 < deficit_peak < n:
            required.append(deficit_peak)
        if tie_idx is not None and 0 < tie_idx < n:
            required.append(tie_idx)
    elif archetype == "wire_to_wire":
        flmi = find_first_meaningful_lead_moment(moments, league_code=league_code)
        if flmi is not None and 0 < flmi < n:
            required.append(flmi)
    elif archetype == "late_separation":
        # The separation moment is the first post-period-3/4 first_meaningful_lead.
        # Approximate by selecting the first scoring run start in the final period.
        flmi = find_first_meaningful_lead_moment(moments, league_code=league_code)
        if flmi is not None and 0 < flmi < n:
            required.append(flmi)
        scoring_runs = find_scoring_runs(moments, league_code=league_code)
        if scoring_runs:
            last_run_start = scoring_runs[-1][0]
            if 0 < last_run_start < n:
                required.append(last_run_start)

    selected_set = set(selected)
    for idx in required:
        if idx in selected_set:
            continue
        # Archetype-required pivots take precedence over priority — drop the
        # lowest-priority (highest priority-number) selected split, breaking
        # ties on later index for determinism.
        if len(selected_set) >= needed_splits and selected_set:
            sacrificable = max(
                selected_set,
                key=lambda s: (candidates.get(s, _PRIORITY_PERIOD), s),
            )
            selected_set.remove(sacrificable)
        selected_set.add(idx)

    return sorted(selected_set)


def find_split_points(
    moments: list[dict[str, Any]],
    target_blocks: int,
    league_code: str = "NBA",
    archetype: str | None = None,
) -> list[int]:
    """Find optimal split points using game-state triggers.

    Trigger priority (highest first):
        1. Lead change
        2. First meaningful lead creation (NBA 6+, MLB 2+ runs)
        3. Scoring run start/end
        4. Comeback deficit peak / tie-flip
        5. OT/SO start (NHL only)
        6. Period boundary — demoted; only kept when it coincides with one of
           the above within ±1 moment.

    Archetype-aware overrides ensure narratively required splits survive the
    priority cut: ``comeback`` mandates deficit-peak + flip, ``wire_to_wire``
    mandates the first-lead moment, ``low_event`` caps total splits at 3.

    Returns indices where new blocks should start.
    """
    n = len(moments)
    if n <= target_blocks:
        return list(range(1, n))

    if archetype == "low_event":
        target_blocks = min(target_blocks, _LOW_EVENT_MAX_BOUNDARIES + 1)

    candidates = _collect_game_state_candidates(moments, league_code)
    state_change_indices = set(candidates.keys())
    _apply_period_boundaries(candidates, moments)

    needed_splits = target_blocks - 1

    # Sort candidates by priority then by index — highest-priority game-state
    # triggers (lead changes, first meaningful lead) must outrank structural
    # SETUP/RESOLUTION carve-outs in short games where the priority-1 trigger
    # may sit outside the n//5 window.
    sorted_candidates = sorted(candidates.keys(), key=lambda x: (candidates[x], x))

    selected: list[int] = []
    min_spacing = max(1, n // (target_blocks + 1))

    for c in sorted_candidates:
        if len(selected) >= needed_splits:
            break
        if any(abs(c - s) < min_spacing for s in selected):
            continue
        selected.append(c)

    state_driven_count = len(selected)

    # Ensure setup/resolution coverage so the narrative still has a clear
    # beginning and end. If neither end of the game has a selected split, add
    # an even-spaced fallback near the n//5 / 4n//5 marks.
    setup_end = max(1, n // 5)
    resolution_start = n - max(1, n // 5)
    has_setup = any(0 < s <= setup_end for s in selected)
    has_resolution = any(resolution_start <= s < n for s in selected)
    setup_resolution_filler = 0
    if not has_setup and len(selected) < needed_splits:
        selected.append(setup_end)
        setup_resolution_filler += 1
    if not has_resolution and len(selected) < needed_splits:
        selected.append(resolution_start)
        setup_resolution_filler += 1

    # Top up with evenly distributed splits if still short — only when we
    # genuinely couldn't find enough game-state candidates. The brief flags
    # arbitrary time buckets as the symptom that motivated the rebuild, so
    # we emit a structured log every time this fires; observability lets
    # ops surface games that fell back to even spacing without breaking
    # them in production.
    even_spaced_filler = 0
    if len(selected) < needed_splits:
        interval = n / (needed_splits + 1)
        for i in range(1, needed_splits + 1):
            if len(selected) >= needed_splits:
                break
            split = int(i * interval)
            if 0 < split < n and split not in selected:
                if not any(abs(split - s) < max(1, min_spacing - 1) for s in selected):
                    selected.append(split)
                    even_spaced_filler += 1

    if setup_resolution_filler or even_spaced_filler:
        logger.info(
            "split_points_time_bucket_fallback",
            extra={
                "league_code": league_code,
                "archetype": archetype,
                "moment_count": n,
                "target_blocks": target_blocks,
                "needed_splits": needed_splits,
                "state_driven_splits": state_driven_count,
                "setup_resolution_filler": setup_resolution_filler,
                "even_spaced_filler": even_spaced_filler,
            },
        )

    selected = sorted(set(selected))[:needed_splits]
    selected = _enforce_archetype_required_splits(
        selected, candidates, moments, league_code, archetype, needed_splits
    )
    selected = _filter_orphan_period_boundaries(
        selected, moments, state_change_indices
    )

    return selected


def find_weighted_split_points(
    moments: list[dict[str, Any]],
    target_blocks: int,
    quarter_weights: dict[str, float],
    league_code: str = "NBA",
    archetype: str | None = None,
) -> list[int]:
    """Drama-weighted split distribution.

    Delegates the core weighted-allocation work to
    :func:`weighted_splits.find_weighted_split_points` (preserving its drama
    monotonicity, back-loaded allocation, and Q1 hard-cap invariants).

    Period-end placements live by design here: drama is allocated per quarter
    and quarter transitions are the structural seams of that allocation.
    The orphan-period filter therefore applies only to the trigger-driven
    :func:`find_split_points` path, not to weighted distribution. Archetype
    overrides are still applied so narratively required pivots survive.
    """
    if archetype == "low_event":
        target_blocks = min(target_blocks, _LOW_EVENT_MAX_BOUNDARIES + 1)

    raw_splits = _weighted_split_points_inner(
        moments, target_blocks, quarter_weights, league_code
    )

    candidates = _collect_game_state_candidates(moments, league_code)
    needed_splits = target_blocks - 1
    return _enforce_archetype_required_splits(
        list(raw_splits), candidates, moments, league_code, archetype, needed_splits
    )
