"""Phase boundary computation for game timeline segmentation.

Contains game-end calculations and phase boundary computations
for NBA, NCAAB, NHL, and MLB. Used by NORMALIZE_PBP to assign plays
to narrative phases with synthetic timestamps.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from ....db.sports import SportsGamePlay
from ....services.timeline_types import (
    # MLB Constants
    MLB_EXTRAS_INNING_REAL_SECONDS,
    MLB_INNING_REAL_SECONDS,
    MLB_REGULATION_REAL_SECONDS,
    # NBA Constants
    NBA_HALFTIME_REAL_SECONDS,
    NBA_QUARTER_REAL_SECONDS,
    NBA_REGULATION_REAL_SECONDS,
    # NCAAB Constants
    NCAAB_HALF_REAL_SECONDS,
    NCAAB_HALFTIME_REAL_SECONDS,
    NCAAB_REGULATION_REAL_SECONDS,
    # NHL Constants
    NHL_INTERMISSION_REAL_SECONDS,
    NHL_PERIOD_REAL_SECONDS,
    NHL_REGULATION_REAL_SECONDS,
    # Social windows
    SOCIAL_PREGAME_WINDOW_SECONDS,
)


def nba_game_end(
    game_start: datetime, plays: Sequence[SportsGamePlay]
) -> datetime:
    """Calculate actual game end time based on plays."""
    max_quarter = 4
    for play in plays:
        if play.quarter and play.quarter > max_quarter:
            max_quarter = play.quarter

    if max_quarter <= 4:
        return game_start + timedelta(seconds=NBA_REGULATION_REAL_SECONDS)

    ot_count = max_quarter - 4
    return game_start + timedelta(
        seconds=NBA_REGULATION_REAL_SECONDS + ot_count * 15 * 60
    )


def ncaab_game_end(
    game_start: datetime, plays: Sequence[SportsGamePlay]
) -> datetime:
    """Calculate NCAAB game end time based on plays."""
    max_period = 2
    for play in plays:
        if play.quarter and play.quarter > max_period:
            max_period = play.quarter

    if max_period <= 2:
        return game_start + timedelta(seconds=NCAAB_REGULATION_REAL_SECONDS)

    ot_count = max_period - 2
    return game_start + timedelta(
        seconds=NCAAB_REGULATION_REAL_SECONDS + ot_count * 10 * 60
    )


def nhl_game_end(
    game_start: datetime, plays: Sequence[SportsGamePlay]
) -> datetime:
    """Calculate NHL game end time based on plays."""
    max_period = 3
    for play in plays:
        if play.quarter and play.quarter > max_period:
            max_period = play.quarter

    if max_period <= 3:
        return game_start + timedelta(seconds=NHL_REGULATION_REAL_SECONDS)

    ot_count = max_period - 3
    return game_start + timedelta(
        seconds=NHL_REGULATION_REAL_SECONDS + ot_count * 10 * 60
    )


def mlb_game_end(
    game_start: datetime, plays: Sequence[SportsGamePlay]
) -> datetime:
    """Calculate MLB game end time based on plays."""
    max_inning = 9
    for play in plays:
        if play.quarter and play.quarter > max_inning:
            max_inning = play.quarter

    if max_inning <= 9:
        return game_start + timedelta(seconds=MLB_REGULATION_REAL_SECONDS)

    extra_innings = max_inning - 9
    return game_start + timedelta(
        seconds=MLB_REGULATION_REAL_SECONDS
        + extra_innings * MLB_EXTRAS_INNING_REAL_SECONDS
    )


def compute_mlb_phase_boundaries(
    game_start: datetime, has_extras: bool = False, extra_innings: int = 0
) -> dict[str, tuple[datetime, datetime]]:
    """Compute start/end times for each MLB narrative phase.

    MLB has 9 innings with no intermissions (continuous play).
    """
    boundaries: dict[str, tuple[datetime, datetime]] = {}

    # Pregame: 2 hours before to game start
    pregame_start = game_start - timedelta(seconds=SOCIAL_PREGAME_WINDOW_SECONDS)
    boundaries["pregame"] = (pregame_start, game_start)

    # 9 regulation innings
    cursor = game_start
    for i in range(1, 10):
        inn_end = cursor + timedelta(seconds=MLB_INNING_REAL_SECONDS)
        boundaries[f"inn{i}"] = (cursor, inn_end)
        cursor = inn_end

    # Extra innings
    if has_extras and extra_innings > 0:
        for i in range(1, extra_innings + 1):
            inn_end = cursor + timedelta(seconds=MLB_EXTRAS_INNING_REAL_SECONDS)
            boundaries[f"ot{i}"] = (cursor, inn_end)
            cursor = inn_end

    boundaries["postgame"] = (cursor, cursor + timedelta(hours=2))

    return boundaries


def compute_phase_boundaries(
    game_start: datetime, has_overtime: bool = False
) -> dict[str, tuple[datetime, datetime]]:
    """Compute start/end times for each narrative phase."""
    boundaries: dict[str, tuple[datetime, datetime]] = {}

    # Pregame: 2 hours before to game start
    pregame_start = game_start - timedelta(seconds=SOCIAL_PREGAME_WINDOW_SECONDS)
    boundaries["pregame"] = (pregame_start, game_start)

    # Q1
    q1_start = game_start
    q1_end = game_start + timedelta(seconds=NBA_QUARTER_REAL_SECONDS)
    boundaries["q1"] = (q1_start, q1_end)

    # Q2
    q2_start = q1_end
    q2_end = q2_start + timedelta(seconds=NBA_QUARTER_REAL_SECONDS)
    boundaries["q2"] = (q2_start, q2_end)

    # Halftime
    halftime_start = q2_end
    halftime_end = halftime_start + timedelta(seconds=NBA_HALFTIME_REAL_SECONDS)
    boundaries["halftime"] = (halftime_start, halftime_end)

    # Q3
    q3_start = halftime_end
    q3_end = q3_start + timedelta(seconds=NBA_QUARTER_REAL_SECONDS)
    boundaries["q3"] = (q3_start, q3_end)

    # Q4
    q4_start = q3_end
    q4_end = q4_start + timedelta(seconds=NBA_QUARTER_REAL_SECONDS)
    boundaries["q4"] = (q4_start, q4_end)

    # Overtime periods (if applicable)
    if has_overtime:
        ot_start = q4_end
        for i in range(1, 5):  # Up to 4 OT periods
            ot_end = ot_start + timedelta(seconds=15 * 60)
            boundaries[f"ot{i}"] = (ot_start, ot_end)
            ot_start = ot_end
        boundaries["postgame"] = (ot_start, ot_start + timedelta(hours=2))
    else:
        boundaries["postgame"] = (q4_end, q4_end + timedelta(hours=2))

    return boundaries


def compute_ncaab_phase_boundaries(
    game_start: datetime, has_overtime: bool = False
) -> dict[str, tuple[datetime, datetime]]:
    """Compute start/end times for each NCAAB narrative phase."""
    boundaries: dict[str, tuple[datetime, datetime]] = {}

    # Pregame: 2 hours before to game start
    pregame_start = game_start - timedelta(seconds=SOCIAL_PREGAME_WINDOW_SECONDS)
    boundaries["pregame"] = (pregame_start, game_start)

    # H1 (first half)
    h1_start = game_start
    h1_end = game_start + timedelta(seconds=NCAAB_HALF_REAL_SECONDS)
    boundaries["h1"] = (h1_start, h1_end)

    # Halftime
    halftime_start = h1_end
    halftime_end = halftime_start + timedelta(seconds=NCAAB_HALFTIME_REAL_SECONDS)
    boundaries["halftime"] = (halftime_start, halftime_end)

    # H2 (second half)
    h2_start = halftime_end
    h2_end = h2_start + timedelta(seconds=NCAAB_HALF_REAL_SECONDS)
    boundaries["h2"] = (h2_start, h2_end)

    # Overtime periods (if applicable)
    if has_overtime:
        ot_start = h2_end
        for i in range(1, 5):  # Up to 4 OT periods
            ot_end = ot_start + timedelta(seconds=10 * 60)  # ~10 min real per OT
            boundaries[f"ot{i}"] = (ot_start, ot_end)
            ot_start = ot_end
        boundaries["postgame"] = (ot_start, ot_start + timedelta(hours=2))
    else:
        boundaries["postgame"] = (h2_end, h2_end + timedelta(hours=2))

    return boundaries


def compute_nhl_phase_boundaries(
    game_start: datetime,
    has_overtime: bool = False,
    has_shootout: bool = False,
) -> dict[str, tuple[datetime, datetime]]:
    """Compute start/end times for each NHL narrative phase.

    NHL has 3 periods with 2 intermissions, plus optional OT and shootout.
    """
    boundaries: dict[str, tuple[datetime, datetime]] = {}

    # Pregame: 2 hours before to game start
    pregame_start = game_start - timedelta(seconds=SOCIAL_PREGAME_WINDOW_SECONDS)
    boundaries["pregame"] = (pregame_start, game_start)

    # P1 (first period)
    p1_start = game_start
    p1_end = game_start + timedelta(seconds=NHL_PERIOD_REAL_SECONDS)
    boundaries["p1"] = (p1_start, p1_end)

    # First intermission
    int1_start = p1_end
    int1_end = int1_start + timedelta(seconds=NHL_INTERMISSION_REAL_SECONDS)
    boundaries["int1"] = (int1_start, int1_end)

    # P2 (second period)
    p2_start = int1_end
    p2_end = p2_start + timedelta(seconds=NHL_PERIOD_REAL_SECONDS)
    boundaries["p2"] = (p2_start, p2_end)

    # Second intermission
    int2_start = p2_end
    int2_end = int2_start + timedelta(seconds=NHL_INTERMISSION_REAL_SECONDS)
    boundaries["int2"] = (int2_start, int2_end)

    # P3 (third period)
    p3_start = int2_end
    p3_end = p3_start + timedelta(seconds=NHL_PERIOD_REAL_SECONDS)
    boundaries["p3"] = (p3_start, p3_end)

    # Overtime (if applicable)
    if has_overtime:
        ot_start = p3_end
        ot_end = ot_start + timedelta(seconds=10 * 60)  # ~10 min real for OT
        boundaries["ot"] = (ot_start, ot_end)
        last_end = ot_end
    else:
        last_end = p3_end

    # Shootout (if applicable)
    if has_shootout:
        so_start = last_end
        so_end = so_start + timedelta(seconds=10 * 60)  # ~10 min for shootout
        boundaries["shootout"] = (so_start, so_end)
        last_end = so_end

    boundaries["postgame"] = (last_end, last_end + timedelta(hours=2))

    return boundaries
