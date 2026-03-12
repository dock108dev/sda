"""Split point algorithms for GROUP_BLOCKS stage.

Contains functions for finding optimal split points to divide moments into blocks:
- Regular split point detection based on lead changes, scoring runs, and periods
- Blowout game compression

Drama-weighted split point distribution lives in weighted_splits.py.
"""

from __future__ import annotations

import logging
from typing import Any

from .block_analysis import (
    find_lead_change_indices,
    find_period_boundaries,
    find_scoring_runs,
)
from .block_types import MIN_BLOCKS
from .weighted_splits import find_weighted_split_points  # noqa: F401 — re-export

# Blowout games get fewer blocks (less narrative needed)
BLOWOUT_MAX_BLOCKS = 5

logger = logging.getLogger(__name__)


def compress_blowout_blocks(
    moments: list[dict[str, Any]],
    decisive_idx: int,
    garbage_time_idx: int | None,
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

    Returns:
        List of split point indices
    """
    n = len(moments)
    split_points: list[int] = []

    # Ensure we have at least MIN_BLOCKS
    # For blowout: [SETUP][MOMENTUM_SHIFT][RESPONSE or compress][RESOLUTION]

    if decisive_idx is None:
        decisive_idx = n // 3  # Default to 1/3 mark

    # First split: After SETUP (first ~15-20% of moments, but before decisive)
    setup_end = min(max(1, n // 6), decisive_idx - 1)
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


def find_split_points(
    moments: list[dict[str, Any]],
    target_blocks: int,
) -> list[int]:
    """Find optimal split points for dividing moments into blocks.

    Priority for split points:
    1. Lead changes
    2. Scoring runs
    3. Period boundaries
    4. Even distribution

    Returns indices where new blocks should start.
    """
    n = len(moments)
    if n <= target_blocks:
        # Each moment is its own block
        return list(range(1, n))

    # Collect candidate split points with priorities
    lead_changes = find_lead_change_indices(moments)
    scoring_runs = find_scoring_runs(moments)
    period_boundaries = find_period_boundaries(moments)

    # Build set of all candidate points with priorities
    candidates: dict[int, int] = {}  # index -> priority (lower = better)

    for idx in lead_changes:
        if 0 < idx < n:
            candidates[idx] = 1  # Highest priority

    for start, end, _ in scoring_runs:
        if 0 < start < n:
            candidates[start] = candidates.get(start, 2)
        if 0 < end + 1 < n:
            candidates[end + 1] = candidates.get(end + 1, 2)

    for idx in period_boundaries:
        if 0 < idx < n:
            candidates[idx] = candidates.get(idx, 3)

    # We need target_blocks - 1 split points (to create target_blocks blocks)
    needed_splits = target_blocks - 1

    # Sort candidates by priority then by index
    sorted_candidates = sorted(candidates.keys(), key=lambda x: (candidates[x], x))

    # Select split points ensuring good distribution
    selected: list[int] = []

    # First, reserve positions for SETUP (first ~20% of moments) and RESOLUTION (last ~20%)
    setup_end = max(1, n // 5)
    resolution_start = n - max(1, n // 5)

    # Add split at end of setup section
    setup_split = None
    for c in sorted_candidates:
        if 1 <= c <= setup_end:
            setup_split = c
            break
    if setup_split is None:
        setup_split = setup_end
    selected.append(setup_split)

    # Add split at start of resolution section
    resolution_split = None
    for c in sorted_candidates:
        if resolution_start <= c < n:
            resolution_split = c
            break
    if resolution_split is None:
        resolution_split = resolution_start
    if resolution_split != setup_split:
        selected.append(resolution_split)

    # Fill in remaining splits from candidates
    for c in sorted_candidates:
        if len(selected) >= needed_splits:
            break
        if c not in selected:
            # Ensure minimum spacing between splits
            too_close = any(abs(c - s) < n // (target_blocks + 1) for s in selected)
            if not too_close:
                selected.append(c)

    # If we still need more splits, add evenly distributed ones
    if len(selected) < needed_splits:
        interval = n / (needed_splits + 1)
        for i in range(1, needed_splits + 1):
            split = int(i * interval)
            if split not in selected and 0 < split < n:
                selected.append(split)
            if len(selected) >= needed_splits:
                break

    # Sort and limit to needed count
    selected = sorted(set(selected))[:needed_splits]

    return selected
