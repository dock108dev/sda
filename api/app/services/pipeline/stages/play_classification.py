"""Play type classification for moment generation.

This module provides functions to classify plays by type:
turnovers, stoppages, period boundaries, and notable plays.
"""

from __future__ import annotations

from typing import Any

from .moment_types import (
    NOTABLE_PLAY_TYPES,
    STOPPAGE_PLAY_TYPES,
    TURNOVER_PLAY_TYPES,
)


def is_turnover_play(event: dict[str, Any]) -> bool:
    """Detect if this play is a turnover/possession change.

    Args:
        event: The normalized PBP event

    Returns:
        True if this is a turnover play
    """
    play_type = (event.get("play_type") or "").lower().replace(" ", "_")
    description = (event.get("description") or "").lower()

    # Check explicit play_type
    if play_type in TURNOVER_PLAY_TYPES:
        return True

    # Check description for turnover indicators
    turnover_keywords = ["turnover", "steal", "lost ball", "bad pass", "traveling"]
    return bool(any(kw in description for kw in turnover_keywords))


def is_period_boundary(
    current_event: dict[str, Any],
    previous_event: dict[str, Any] | None,
) -> bool:
    """Detect if this play starts a new period.

    Args:
        current_event: The current normalized PBP event
        previous_event: The previous event (None for first play)

    Returns:
        True if period changed, False otherwise
    """
    if previous_event is None:
        return False

    prev_quarter = previous_event.get("quarter") or 1
    curr_quarter = current_event.get("quarter") or 1

    return curr_quarter != prev_quarter


def is_stoppage_play(event: dict[str, Any]) -> bool:
    """Detect if this play is a stoppage (timeout, review, etc.).

    Args:
        event: The normalized PBP event

    Returns:
        True if this is a stoppage play, False otherwise
    """
    play_type = (event.get("play_type") or "").lower().replace(" ", "_")
    description = (event.get("description") or "").lower()

    # Check explicit play_type
    if play_type in STOPPAGE_PLAY_TYPES:
        return True

    # Check description for timeout indicators
    return "timeout" in description


def is_notable_play(event: dict[str, Any]) -> bool:
    """Check if a play has a notable play_type.

    Args:
        event: The normalized PBP event

    Returns:
        True if the play_type is in NOTABLE_PLAY_TYPES
    """
    play_type = (event.get("play_type") or "").lower().replace(" ", "_")
    return play_type in NOTABLE_PLAY_TYPES


def should_start_new_moment(
    current_event: dict[str, Any],
    previous_event: dict[str, Any] | None,
    current_moment_size: int,
) -> bool:
    """Determine if we should start a new moment before this play.

    BOUNDARY RULES (in priority order):
    1. Period boundary: Always start new moment at period change
    2. Hard maximum: Start new moment if current would exceed SOFT_CAP_PLAYS
    3. After scoring: Previous play was a scoring play
    4. After stoppage: Previous play was a timeout/review

    Args:
        current_event: The current normalized PBP event
        previous_event: The previous event (None for first play)
        current_moment_size: Number of plays in current moment

    Returns:
        True if a new moment should start, False otherwise
    """
    from .moment_types import SOFT_CAP_PLAYS

    # First play always starts first moment
    if previous_event is None:
        return True

    # Rule 1: Period boundary - always start new moment
    if is_period_boundary(current_event, previous_event):
        return True

    # Rule 2: Hard maximum exceeded
    if current_moment_size >= SOFT_CAP_PLAYS:
        return True

    # Rule 4: Previous play was a stoppage
    return bool(is_stoppage_play(previous_event))
