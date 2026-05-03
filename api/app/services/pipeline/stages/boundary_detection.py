"""Boundary detection for moment generation.

This module handles the detection of moment boundaries, including
hard (non-negotiable) and soft (preferred) boundary conditions.
"""

from __future__ import annotations

from typing import Any

from .explicit_selection import select_explicitly_narrated_plays
from .moment_types import (
    ABSOLUTE_MAX_PLAYS,
    MAX_EXPLICIT_PLAYS_PER_MOMENT,
    MIN_PLAYS_BEFORE_SOFT_CLOSE,
    PREFERRED_EXPLICIT_PLAYS,
    SOFT_CAP_PLAYS,
    BoundaryReason,
)
from .play_classification import is_stoppage_play, is_turnover_play
from .score_detection import is_lead_change_play, is_scoring_play


def should_force_close_moment(
    current_moment_plays: list[dict[str, Any]],
    current_event: dict[str, Any],
    previous_event: dict[str, Any] | None,
    all_events: list[dict[str, Any]],
    moment_start_idx: int,
    first_meaningful_lead_play_idx: int | None = None,
) -> tuple[bool, BoundaryReason | None]:
    """Check if a HARD boundary condition requires closing the moment.

    HARD conditions are non-negotiable and always force closure.

    Args:
        current_moment_plays: Plays currently in the moment (including current)
        current_event: The current event just added
        previous_event: The previous event (None for first play)
        all_events: All events for explicit play counting
        moment_start_idx: Start index of current moment
        first_meaningful_lead_play_idx: Play index of the play that first crossed
            the league's lead-created threshold (NBA 6 pts, MLB 2 runs, …). When
            the current event matches this index, the moment is force-closed so
            the lead-creation moment becomes its own narrative beat.

    Returns:
        (should_close, reason) tuple
    """
    # HARD: Absolute max plays reached (safety valve)
    if len(current_moment_plays) >= ABSOLUTE_MAX_PLAYS:
        return True, BoundaryReason.ABSOLUTE_MAX_PLAYS

    # HARD: Lead change occurred
    if previous_event and is_lead_change_play(current_event, previous_event):
        return True, BoundaryReason.LEAD_CHANGE

    # HARD: First meaningful lead creation (game-state trigger from score timeline).
    # Closes after this play so the lead-creation moment is anchored — downstream
    # block-level boundary selection consumes the same trigger via score_timeline.
    if (
        first_meaningful_lead_play_idx is not None
        and current_event.get("play_index") == first_meaningful_lead_play_idx
    ):
        return True, BoundaryReason.FIRST_MEANINGFUL_LEAD

    # HARD: Would create >2 explicitly narrated plays
    # Check what the explicit play count would be
    narrated = select_explicitly_narrated_plays(
        current_moment_plays, all_events, moment_start_idx
    )
    if len(narrated) > MAX_EXPLICIT_PLAYS_PER_MOMENT:
        return True, BoundaryReason.EXPLICIT_PLAY_OVERFLOW

    return False, None


def should_prefer_close_moment(
    current_moment_plays: list[dict[str, Any]],
    current_event: dict[str, Any],
    previous_event: dict[str, Any] | None,
    all_events: list[dict[str, Any]],
    moment_start_idx: int,
) -> tuple[bool, BoundaryReason | None]:
    """Check if a SOFT boundary condition suggests closing the moment.

    SOFT conditions prefer closing but can be overridden by merge eligibility.
    With larger moments (30-50 plays), we're more permissive about soft boundaries.

    Args:
        current_moment_plays: Plays currently in the moment (including current)
        current_event: The current event just added
        previous_event: The previous event (None for first play)
        all_events: All events for explicit play counting
        moment_start_idx: Start index of current moment

    Returns:
        (should_close, reason) tuple
    """
    play_count = len(current_moment_plays)

    # SOFT: Soft cap reached - always prefer close at this point
    if play_count >= SOFT_CAP_PLAYS:
        return True, BoundaryReason.SOFT_CAP_REACHED

    # For smaller moments, we're more permissive to encourage growth
    # Only apply scoring/stoppage/turnover soft boundaries after minimum threshold
    if play_count < MIN_PLAYS_BEFORE_SOFT_CLOSE:
        # Still check for too many explicit plays even in small moments
        narrated = select_explicitly_narrated_plays(
            current_moment_plays, all_events, moment_start_idx
        )
        if len(narrated) > PREFERRED_EXPLICIT_PLAYS:
            return True, BoundaryReason.SECOND_EXPLICIT_PLAY
        return False, None

    # SOFT: Stoppage play (timeouts, reviews) - good natural break points
    if is_stoppage_play(current_event):
        return True, BoundaryReason.STOPPAGE

    # SOFT: Only close on scoring plays after reaching 2/3 of soft cap
    # This allows scoring runs to be captured in single moments
    if play_count >= (SOFT_CAP_PLAYS * 2 // 3):
        if previous_event and is_scoring_play(current_event, previous_event):
            return True, BoundaryReason.SCORING_PLAY

    # SOFT: Turnovers are weaker boundaries - only close if moment is moderately sized
    if play_count >= (SOFT_CAP_PLAYS // 2) and is_turnover_play(current_event):
        return True, BoundaryReason.POSSESSION_CHANGE

    # SOFT: Too many explicitly narrated plays (now allows up to PREFERRED_EXPLICIT_PLAYS)
    narrated = select_explicitly_narrated_plays(
        current_moment_plays, all_events, moment_start_idx
    )
    if len(narrated) > PREFERRED_EXPLICIT_PLAYS:
        return True, BoundaryReason.SECOND_EXPLICIT_PLAY

    return False, None


def is_merge_eligible(
    current_moment_plays: list[dict[str, Any]],
    current_event: dict[str, Any],
    previous_event: dict[str, Any] | None,
    next_event: dict[str, Any] | None,
) -> bool:
    """Check if game flow suggests we should continue merging plays.

    Merge eligibility can override SOFT (but not HARD) boundary conditions.
    Note: SOFT_CAP_REACHED is explicitly excluded from override in the caller,
    so we don't check soft cap here.

    With larger target moments (30-50 plays), we're more aggressive about merging
    to create richer, more comprehensive moment narratives.

    Conditions for merge eligibility:
    - Small/medium moments (< 2/3 of SOFT_CAP) encourage merge within same period
    - Larger moments are more selective but still allow continuation
    - Game flow appears continuous (same period)

    Args:
        current_moment_plays: Plays currently in the moment
        current_event: The current event
        previous_event: The previous event
        next_event: The next event (for lookahead)

    Returns:
        True if merge should be encouraged
    """
    play_count = len(current_moment_plays)

    # Small/medium moments should encourage merging within the same period
    # This helps build larger, richer moments
    merge_threshold = (SOFT_CAP_PLAYS * 2) // 3  # ~20 plays

    if play_count < merge_threshold:
        if next_event:
            curr_period = current_event.get("quarter") or 1
            next_period = next_event.get("quarter") or 1
            if curr_period == next_period:
                return True
        return False

    # For larger moments (20+ plays), still allow merging but be more selective
    # Only discourage merge if there have been multiple scoring plays AND
    # a significant score change (6+ points total)
    # Note: We only reach here when play_count >= merge_threshold (early return above)
    scoring_play_count = 0
    total_pts_scored = 0

    if len(current_moment_plays) >= 2:
        first_play = current_moment_plays[0]
        last_play = current_moment_plays[-1]
        home_pts = (last_play.get("home_score") or 0) - (first_play.get("home_score") or 0)
        away_pts = (last_play.get("away_score") or 0) - (first_play.get("away_score") or 0)
        total_pts_scored = home_pts + away_pts

    for j in range(1, len(current_moment_plays)):
        prev = current_moment_plays[j - 1]
        curr = current_moment_plays[j]
        if is_scoring_play(curr, prev):
            scoring_play_count += 1

    # If significant scoring has occurred, discourage further merging
    if scoring_play_count >= 4 and total_pts_scored >= 10:
        return False

    # If next event is in the same period and game is flowing, encourage merge
    if next_event:
        curr_period = current_event.get("quarter") or 1
        next_period = next_event.get("quarter") or 1
        if curr_period == next_period:
            return True

    return False
