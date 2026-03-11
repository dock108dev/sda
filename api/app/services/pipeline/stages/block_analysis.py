"""Block analysis helpers for group_blocks stage.

Pure analysis functions that operate on moment data to identify:
- Lead changes
- Scoring runs
- Period boundaries
- Blowout detection
- Garbage time detection
"""

from __future__ import annotations

from typing import Any

from .league_config import get_config

# Sustained-period requirement for blowout detection (not league-variable).
BLOWOUT_SUSTAINED_PERIODS = 1


def count_lead_changes(moments: list[dict[str, Any]]) -> int:
    """Count lead changes across all moments."""
    lead_changes = 0
    prev_leader: int | None = None  # -1 = away, 0 = tie, 1 = home

    for moment in moments:
        score_after = moment.get("score_after", [0, 0])
        home, away = score_after[0], score_after[1]

        if home > away:
            current_leader = 1
        elif away > home:
            current_leader = -1
        else:
            current_leader = 0

        if prev_leader is not None and prev_leader != 0 and current_leader != 0:
            if prev_leader != current_leader:
                lead_changes += 1

        if current_leader != 0:
            prev_leader = current_leader

    return lead_changes


def find_lead_change_indices(moments: list[dict[str, Any]]) -> list[int]:
    """Find indices of moments where lead changes occur."""
    lead_change_indices: list[int] = []
    prev_leader: int | None = None

    for i, moment in enumerate(moments):
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])

        home_before, away_before = score_before[0], score_before[1]
        if home_before > away_before:
            leader_before = 1
        elif away_before > home_before:
            leader_before = -1
        else:
            leader_before = 0

        home_after, away_after = score_after[0], score_after[1]
        if home_after > away_after:
            leader_after = 1
        elif away_after > home_after:
            leader_after = -1
        else:
            leader_after = 0

        if leader_before != 0 and leader_after != 0 and leader_before != leader_after:
            lead_change_indices.append(i)

        prev_leader = leader_after if leader_after != 0 else prev_leader

    return lead_change_indices


def find_scoring_runs(
    moments: list[dict[str, Any]],
    min_run_size: int = 8,
    league_code: str = "NBA",
) -> list[tuple[int, int, int]]:
    """Find significant scoring runs (unanswered points).

    Returns list of (start_idx, end_idx, run_size) tuples.
    """
    runs: list[tuple[int, int, int]] = []

    current_run_start = 0
    current_run_team: int | None = None
    current_run_points = 0

    for i, moment in enumerate(moments):
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])

        home_delta = score_after[0] - score_before[0]
        away_delta = score_after[1] - score_before[1]

        if home_delta > 0 and away_delta == 0:
            scoring_team = 1
            points = home_delta
        elif away_delta > 0 and home_delta == 0:
            scoring_team = -1
            points = away_delta
        elif home_delta > 0 and away_delta > 0:
            if current_run_points >= min_run_size:
                runs.append((current_run_start, i - 1, current_run_points))
            current_run_team = None
            current_run_points = 0
            current_run_start = i + 1
            continue
        else:
            continue

        if current_run_team is None:
            current_run_team = scoring_team
            current_run_start = i
            current_run_points = points
        elif scoring_team == current_run_team:
            current_run_points += points
        else:
            if current_run_points >= min_run_size:
                runs.append((current_run_start, i - 1, current_run_points))
            current_run_team = scoring_team
            current_run_start = i
            current_run_points = points

    if current_run_points >= min_run_size:
        runs.append((current_run_start, len(moments) - 1, current_run_points))

    return runs


def find_period_boundaries(moments: list[dict[str, Any]]) -> list[int]:
    """Find indices where period changes occur."""
    boundaries: list[int] = []

    for i in range(1, len(moments)):
        prev_period = moments[i - 1].get("period", 1)
        curr_period = moments[i].get("period", 1)
        if prev_period != curr_period:
            boundaries.append(i)

    return boundaries


def detect_blowout(
    moments: list[dict[str, Any]],
    league_code: str = "NBA",
) -> tuple[bool, int | None, int]:
    """Detect if game is a blowout and find when it became decisive.

    A blowout is detected when:
    - Margin reaches the league's blowout_margin threshold
    - Margin is sustained for 1+ periods

    Returns:
        Tuple of (is_blowout, decisive_moment_idx, max_margin)
    """
    if not moments:
        return False, None, 0

    cfg = get_config(league_code)
    blowout_threshold = cfg["blowout_margin"]

    decisive_moment_idx: int | None = None
    margin_start_period: int | None = None
    margin_start_idx: int | None = None
    max_margin = 0

    for i, moment in enumerate(moments):
        score_after = moment.get("score_after", [0, 0])
        period = moment.get("period", 1)
        home, away = score_after[0], score_after[1]
        margin = abs(home - away)

        max_margin = max(max_margin, margin)

        if margin >= blowout_threshold:
            if margin_start_period is None:
                margin_start_period = period
                margin_start_idx = i
            else:
                periods_elapsed = period - margin_start_period
                if periods_elapsed >= BLOWOUT_SUSTAINED_PERIODS:
                    decisive_moment_idx = margin_start_idx
                    return True, decisive_moment_idx, max_margin
        else:
            margin_start_period = None
            margin_start_idx = None

    return False, decisive_moment_idx, max_margin


def find_garbage_time_start(
    moments: list[dict[str, Any]],
    league_code: str = "NBA",
) -> int | None:
    """Find when garbage time begins (if at all).

    Garbage time is when:
    - Margin exceeds the league's garbage_time_margin
    - Period is at or beyond the league's garbage_time_period

    Returns:
        Moment index where garbage time starts, or None
    """
    cfg = get_config(league_code)
    gt_margin = cfg["garbage_time_margin"]
    gt_period = cfg["garbage_time_period"]

    for i, moment in enumerate(moments):
        score_after = moment.get("score_after", [0, 0])
        period = moment.get("period", 1)
        home, away = score_after[0], score_after[1]
        margin = abs(home - away)

        if margin >= gt_margin and period >= gt_period:
            return i

    return None
