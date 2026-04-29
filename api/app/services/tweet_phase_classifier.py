"""Tweet phase classification for timeline generation.

Provides league-aware, time-based phase classification and segment mapping
for social media posts relative to game timing.
"""

from __future__ import annotations

from datetime import datetime

from .timeline_phases import estimate_game_end, get_league_timing


def classify_tweet_phase(
    tweet_time: datetime,
    game_start: datetime,
    league_code: str,
    has_overtime: bool = False,
) -> str:
    """Classify a tweet into pregame, in-game, or postgame.

    Classification rules:
    - Pregame: tweet_time < game_start
    - In-game: game_start <= tweet_time <= estimated_game_end + OT_buffer
    - Postgame: tweet_time > estimated_game_end + OT_buffer AND
                tweet_time <= estimated_game_end + 4 hours

    Tweets beyond postgame window return "postgame" but may be deprioritized.

    Args:
        tweet_time: When the tweet was posted
        game_start: Authoritative game start time
        league_code: League code for timing heuristics
        has_overtime: Whether OT is detected

    Returns:
        Phase string: "pregame", "in_game", or "postgame"
    """
    if tweet_time < game_start:
        return "pregame"

    estimated_end = estimate_game_end(game_start, league_code, has_overtime)

    if tweet_time <= estimated_end:
        return "in_game"

    # Everything after game end is postgame
    return "postgame"


def map_tweet_to_segment(
    tweet_time: datetime,
    game_start: datetime,
    league_code: str,
    has_overtime: bool = False,
) -> str:
    """Map an in-game tweet to a specific game segment.

    Computes elapsed_ratio = (tweet_time - game_start) / estimated_game_duration
    Maps ratio to league-appropriate segment (quarter/half/period).

    Segment boundaries are approximate - minor misplacements are acceptable.

    Args:
        tweet_time: When the tweet was posted
        game_start: Authoritative game start time
        league_code: League code for segment mapping
        has_overtime: Whether OT is detected

    Returns:
        Segment string (e.g., "q1", "first_half", "p2")
    """
    league_upper = (league_code or "").upper()

    # Get estimated game duration
    regulation_mins, ot_buffer_mins = get_league_timing(league_code)
    estimated_duration_mins = regulation_mins
    if has_overtime:
        estimated_duration_mins += ot_buffer_mins

    # Calculate elapsed ratio (clamped to [0, 1])
    elapsed = (tweet_time - game_start).total_seconds()
    duration_seconds = estimated_duration_mins * 60

    elapsed_ratio = 0.0 if duration_seconds <= 0 else max(0.0, min(1.0, elapsed / duration_seconds))

    # Map ratio to segment based on league
    if league_upper == "NCAAB":
        return _map_ncaab_segment(elapsed_ratio)
    elif league_upper == "NHL":
        return _map_nhl_segment(elapsed_ratio, has_overtime)
    else:
        # Default to NBA
        return _map_nba_segment(elapsed_ratio)


def _map_ncaab_segment(elapsed_ratio: float) -> str:
    """Map elapsed ratio to NCAAB segment (halves).

    NCAAB has two 20-minute halves with halftime.
    Approximate split: first_half (0-0.45), halftime (0.45-0.55), second_half (0.55-1.0)
    """
    if elapsed_ratio < 0.45:
        return "first_half"
    elif elapsed_ratio < 0.55:
        return "halftime"
    else:
        return "second_half"


def _map_nba_segment(elapsed_ratio: float) -> str:
    """Map elapsed ratio to NBA segment (quarters).

    NBA has four 12-minute quarters with halftime after Q2.
    Approximate splits with halftime buffer.
    """
    if elapsed_ratio < 0.20:
        return "q1"
    elif elapsed_ratio < 0.40:
        return "q2"
    elif elapsed_ratio < 0.50:
        return "halftime"
    elif elapsed_ratio < 0.70:
        return "q3"
    else:
        return "q4"


def _map_nhl_segment(elapsed_ratio: float, has_overtime: bool) -> str:
    """Map elapsed ratio to NHL segment (periods).

    NHL has three 20-minute periods.
    Approximate split: p1 (0-0.33), p2 (0.33-0.66), p3 (0.66-1.0)
    OT/shootout handled separately.
    """
    if has_overtime and elapsed_ratio > 0.95:
        return "ot"

    if elapsed_ratio < 0.33:
        return "p1"
    elif elapsed_ratio < 0.66:
        return "p2"
    else:
        return "p3"


def assign_tweet_phase_and_segment(
    tweet_time: datetime,
    game_start: datetime,
    league_code: str,
    has_overtime: bool = False,
) -> tuple[str, str | None]:
    """Classify tweet and assign segment in one call.

    Args:
        tweet_time: When the tweet was posted
        game_start: Authoritative game start time
        league_code: League code
        has_overtime: Whether OT is detected

    Returns:
        Tuple of (phase, segment) where:
        - phase: "pregame", "in_game", or "postgame"
        - segment: Specific segment for in-game tweets, None for others
    """
    phase = classify_tweet_phase(tweet_time, game_start, league_code, has_overtime)

    if phase == "in_game":
        segment = map_tweet_to_segment(
            tweet_time, game_start, league_code, has_overtime
        )
        return phase, segment

    return phase, None
