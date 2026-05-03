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

from .league_config import LEAGUE_CONFIG, get_config, get_flow_thresholds

# Sustained-period requirement for blowout detection (not league-variable).
BLOWOUT_SUSTAINED_PERIODS = 1


def _lead_created_threshold(league_code: str) -> int:
    """Resolve the lead-created threshold (NBA 6, MLB 2, …).

    Mirrors ``score_timeline.lookup_lead_created_threshold`` but operates
    against block_analysis's existing imports to avoid a circular dependency
    with the helpers package.
    """
    flow = get_flow_thresholds(league_code)
    if "lead_created" in flow:
        return int(flow["lead_created"])
    if "multi_run_inning" in flow:
        return int(flow["multi_run_inning"])
    code = (league_code or "").upper()
    cfg = LEAGUE_CONFIG.get(code, LEAGUE_CONFIG["NBA"])
    return int(cfg.get("meaningful_lead", 6))


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


def find_first_meaningful_lead_moment(
    moments: list[dict[str, Any]],
    league_code: str = "NBA",
) -> int | None:
    """Return the first moment index whose ``score_after`` |lead| reaches the
    league's lead-created threshold (NBA 6, MLB 2, NHL 2 …).

    Used as a block-level boundary candidate: this is the moment where one team
    first builds any real cushion, and the narrative typically pivots there.
    """
    threshold = _lead_created_threshold(league_code)
    for i, moment in enumerate(moments):
        score = moment.get("score_after", [0, 0])
        if abs(score[0] - score[1]) >= threshold:
            return i
    return None


def find_comeback_pivot_moments(
    moments: list[dict[str, Any]],
    league_code: str = "NBA",
) -> tuple[int | None, int | None]:
    """Locate the deficit peak and the tie/flip moment for the eventual winner.

    Determines the eventual winner from the final ``score_after`` and walks the
    moment timeline from the winner's perspective. ``deficit_peak_idx`` is the
    moment where the eventual winner trailed by the most; ``tie_or_flip_idx``
    is the first moment after the peak where the lead returns to 0 or flips
    in the winner's favor. Either value is ``None`` when the game shape does
    not actually involve a comeback (no meaningful deficit, no recovery).

    The deficit must reach the league's ``meaningful_lead`` to qualify — this
    keeps the helper consistent with archetype classification and avoids
    flagging tiny back-and-forth swings as comebacks.
    """
    if not moments:
        return None, None

    final_score = moments[-1].get("score_after", [0, 0])
    if final_score[0] == final_score[1]:
        return None, None

    winner_sign = 1 if final_score[0] > final_score[1] else -1
    code = (league_code or "").upper()
    cfg = LEAGUE_CONFIG.get(code, LEAGUE_CONFIG["NBA"])
    meaningful = int(cfg.get("meaningful_lead", 10))

    deficit_peak_idx: int | None = None
    deficit_peak = 0
    for i, moment in enumerate(moments):
        s = moment.get("score_after", [0, 0])
        signed_lead = (s[0] - s[1]) * winner_sign
        if signed_lead < deficit_peak:
            deficit_peak = signed_lead
            deficit_peak_idx = i

    if deficit_peak_idx is None or abs(deficit_peak) < meaningful:
        return None, None

    tie_idx: int | None = None
    for i in range(deficit_peak_idx + 1, len(moments)):
        s = moments[i].get("score_after", [0, 0])
        signed_lead = (s[0] - s[1]) * winner_sign
        if signed_lead >= 0:
            tie_idx = i
            break

    return deficit_peak_idx, tie_idx


def find_overtime_start_moment(
    moments: list[dict[str, Any]],
    league_code: str = "NBA",
) -> int | None:
    """Return the first moment whose period is past regulation.

    NHL uses a 3-period regulation; NBA / NCAAB use their own. The check is
    purely period-based: the first moment whose ``period`` exceeds the league's
    ``regulation_periods`` is considered the OT/SO entry point.
    """
    code = (league_code or "").upper()
    cfg = LEAGUE_CONFIG.get(code, LEAGUE_CONFIG["NBA"])
    regulation = int(cfg.get("regulation_periods", 4))
    for i, moment in enumerate(moments):
        period = moment.get("period", 1) or 1
        if period > regulation:
            return i
    return None


def find_first_scoring_moment(moments: list[dict[str, Any]]) -> int | None:
    """Return the index of the first moment whose score changed from before to after.

    For NHL this is the "first goal" boundary trigger — the moment that opens
    the scoring sequence. Used by group_split_points for goal-driven flow.
    """
    for i, moment in enumerate(moments):
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])
        if (
            (score_after[0] or 0) > (score_before[0] or 0)
            or (score_after[1] or 0) > (score_before[1] or 0)
        ):
            return i
    return None


def find_tied_state_flip_indices(moments: list[dict[str, Any]]) -> list[int]:
    """Return indices where the tie/lead state crossed zero.

    Captures the two NHL boundary triggers that ``find_lead_change_indices``
    misses by design: tying goals (leader → tied) and go-ahead goals from a
    tied state (tied → leader). ``find_lead_change_indices`` only counts
    leader → other-leader; this helper complements it for goal-sequence-driven
    leagues.
    """
    indices: list[int] = []
    for i, moment in enumerate(moments):
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])

        before_diff = (score_before[0] or 0) - (score_before[1] or 0)
        after_diff = (score_after[0] or 0) - (score_after[1] or 0)

        if before_diff == 0 and after_diff == 0:
            continue
        if (before_diff == 0) != (after_diff == 0):
            indices.append(i)
    return indices


def find_multi_goal_period_end_indices(
    moments: list[dict[str, Any]],
    min_goals: int = 2,
) -> list[int]:
    """Return period-boundary indices for periods that produced ``min_goals`` or more.

    The returned index is the start of the *next* period (matching the
    convention used by :func:`find_period_boundaries`), so it can be used
    directly as a candidate split point.
    """
    if not moments:
        return []

    period_goal_counts: dict[int, int] = {}
    for moment in moments:
        score_before = moment.get("score_before", [0, 0])
        score_after = moment.get("score_after", [0, 0])
        delta = (score_after[0] or 0) - (score_before[0] or 0) + (
            (score_after[1] or 0) - (score_before[1] or 0)
        )
        if delta <= 0:
            continue
        period = moment.get("period", 1) or 1
        period_goal_counts[period] = period_goal_counts.get(period, 0) + delta

    boundaries = find_period_boundaries(moments)
    out: list[int] = []
    for idx in boundaries:
        prev_period = moments[idx - 1].get("period", 1) or 1
        if period_goal_counts.get(prev_period, 0) >= min_goals:
            out.append(idx)
    return out


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
