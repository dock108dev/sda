"""Temporal block matching for embedded tweets.

Wall-clock timing constants and helpers for matching tweets to narrative
blocks based on when they were posted relative to game periods.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .tweet_scorer import BlockTweetAssignment, ScoredTweet

# =============================================================================
# WALL-CLOCK TIMING FOR TWEET MATCHING
# =============================================================================
# These constants use realistic wall-clock estimates (derived from
# *_REGULATION_REAL_MINUTES in timeline_types.py) rather than compressed
# PBP normalization timing.  Tweets have real wall-clock timestamps and
# must be matched using wall-clock period windows.

DEFAULT_TWEET_LAG_SECONDS = 90  # Team accounts typically post 1-2 min after a play

# NBA wall-clock: 165 min regulation, 15 min halftime, ~20 min per OT
_NBA_WALL_QUARTER_SECONDS = int(165 * 60 / 4)  # 2475s = 41.25 min
_NBA_WALL_HALFTIME_SECONDS = 15 * 60            # 900s = 15 min
_NBA_WALL_OT_SECONDS = 20 * 60                  # 1200s = 20 min

# NCAAB wall-clock: 135 min regulation, 20 min halftime, ~15 min per OT
_NCAAB_WALL_HALF_SECONDS = int(135 * 60 / 2)    # 4050s = 67.5 min
_NCAAB_WALL_HALFTIME_SECONDS = 20 * 60          # 1200s = 20 min
_NCAAB_WALL_OT_SECONDS = 15 * 60                # 900s = 15 min

# NHL wall-clock: 165 min regulation, 18 min intermission, ~20 min per OT
_NHL_WALL_PERIOD_SECONDS = int(165 * 60 / 3)    # 3300s = 55 min
_NHL_WALL_INTERMISSION_SECONDS = 18 * 60        # 1080s = 18 min
_NHL_WALL_OT_SECONDS = 20 * 60                  # 1200s = 20 min

# Selection limit (imported here for assign_tweets_to_blocks_by_time)
from .tweet_scorer import MAX_EMBEDDED_TWEETS  # noqa: E402

# =============================================================================
# PBP NORMALIZATION PERIOD START (dispatch)
# =============================================================================


def _period_real_start(game_start: datetime, period: int, league_code: str) -> datetime:
    """Dispatch to league-specific period start calculator.

    NOTE: This uses PBP normalization timing (compressed synthetic timeline).
    For tweet matching use ``_tweet_period_wall_start`` instead, which uses
    realistic wall-clock estimates.

    Args:
        game_start: Tip-off / puck-drop time.
        period: 1-based period number.
        league_code: "NBA", "NHL", or "NCAAB".
    """
    from ....services.timeline_phases import nba_quarter_start, ncaab_period_start, nhl_period_start

    if league_code == "NHL":
        return nhl_period_start(game_start, period)
    if league_code == "NCAAB":
        return ncaab_period_start(game_start, period)
    return nba_quarter_start(game_start, period)


# =============================================================================
# WALL-CLOCK PERIOD START HELPERS (for tweet matching)
# =============================================================================


def _nba_wall_period_start(game_start: datetime, period: int) -> datetime:
    """NBA wall-clock period start.  Q1=1, Q2=2, Q3=3, Q4=4, OT1=5, ..."""
    if period == 1:
        return game_start
    if period == 2:
        return game_start + timedelta(seconds=_NBA_WALL_QUARTER_SECONDS)
    if period == 3:
        return game_start + timedelta(
            seconds=2 * _NBA_WALL_QUARTER_SECONDS + _NBA_WALL_HALFTIME_SECONDS
        )
    if period == 4:
        return game_start + timedelta(
            seconds=3 * _NBA_WALL_QUARTER_SECONDS + _NBA_WALL_HALFTIME_SECONDS
        )
    # Overtime: OT1 = period 5, etc.
    ot_num = period - 4
    regulation_end = 4 * _NBA_WALL_QUARTER_SECONDS + _NBA_WALL_HALFTIME_SECONDS
    return game_start + timedelta(
        seconds=regulation_end + (ot_num - 1) * _NBA_WALL_OT_SECONDS
    )


def _ncaab_wall_period_start(game_start: datetime, period: int) -> datetime:
    """NCAAB wall-clock period start.  H1=1, H2=2, OT1=3, ..."""
    if period == 1:
        return game_start
    if period == 2:
        return game_start + timedelta(
            seconds=_NCAAB_WALL_HALF_SECONDS + _NCAAB_WALL_HALFTIME_SECONDS
        )
    # Overtime
    ot_num = period - 2
    regulation_end = 2 * _NCAAB_WALL_HALF_SECONDS + _NCAAB_WALL_HALFTIME_SECONDS
    return game_start + timedelta(
        seconds=regulation_end + (ot_num - 1) * _NCAAB_WALL_OT_SECONDS
    )


def _nhl_wall_period_start(game_start: datetime, period: int) -> datetime:
    """NHL wall-clock period start.  P1=1, P2=2, P3=3, OT1=4, ..."""
    if period == 1:
        return game_start
    if period == 2:
        return game_start + timedelta(
            seconds=_NHL_WALL_PERIOD_SECONDS + _NHL_WALL_INTERMISSION_SECONDS
        )
    if period == 3:
        return game_start + timedelta(
            seconds=2 * _NHL_WALL_PERIOD_SECONDS + 2 * _NHL_WALL_INTERMISSION_SECONDS
        )
    # Overtime
    ot_num = period - 3
    regulation_end = 3 * _NHL_WALL_PERIOD_SECONDS + 2 * _NHL_WALL_INTERMISSION_SECONDS
    return game_start + timedelta(
        seconds=regulation_end + (ot_num - 1) * _NHL_WALL_OT_SECONDS
    )


def _tweet_period_wall_start(
    game_start: datetime, period: int, league_code: str
) -> datetime:
    """Dispatch to league-specific wall-clock period start calculator.

    Uses realistic wall-clock timing for tweet matching, NOT PBP
    normalization timing.
    """
    if league_code == "NHL":
        return _nhl_wall_period_start(game_start, period)
    if league_code == "NCAAB":
        return _ncaab_wall_period_start(game_start, period)
    return _nba_wall_period_start(game_start, period)


def assign_tweets_to_blocks_by_time(
    scored_tweets: list[ScoredTweet],
    blocks: list[dict[str, Any]],
    game_start: datetime,
    league_code: str,
    tweet_lag_seconds: int = DEFAULT_TWEET_LAG_SECONDS,
) -> list[BlockTweetAssignment]:
    """Assign tweets to blocks by temporal matching.

    For each block, compute its real-time window from period_start.
    When multiple blocks share the same period_start, the period's
    real-time window is subdivided evenly so tweets distribute across
    all blocks rather than collapsing to the last one.

    Per block: highest-scored tweet becomes the display tweet,
    remaining matches go into additional_tweets.

    After assignment, enforces MAX_EMBEDDED_TWEETS global cap:
    if more than 5 blocks have display tweets, only the top 5 by
    score are kept; the rest are demoted to additional_tweets.
    """
    if not blocks:
        return []

    # 1. Compute block time window starts (ordered by window_start, block_index)
    block_starts: list[tuple[int, datetime]] = []
    for block in blocks:
        idx = block.get("block_index", len(block_starts))
        period = block.get("period_start", 1)
        window_start = _tweet_period_wall_start(game_start, period, league_code)
        block_starts.append((idx, window_start))
    block_starts.sort(key=lambda x: (x[1], x[0]))

    # 2. Subdivide when blocks share the same window_start
    groups: list[list[tuple[int, datetime]]] = []
    for entry in block_starts:
        if not groups or entry[1] != groups[-1][0][1]:
            groups.append([entry])
        else:
            groups[-1].append(entry)

    max_period = max(block.get("period_start", 1) for block in blocks)
    final_end = _tweet_period_wall_start(game_start, max_period + 1, league_code)

    subdivided: list[tuple[int, datetime]] = []
    for g_idx, group in enumerate(groups):
        if len(group) == 1:
            subdivided.append(group[0])
            continue
        group_start = group[0][1]
        group_end = groups[g_idx + 1][0][1] if g_idx + 1 < len(groups) else final_end
        span = (group_end - group_start).total_seconds()
        for k, (block_idx, _) in enumerate(group):
            sub_start = group_start + timedelta(seconds=k * span / len(group))
            subdivided.append((block_idx, sub_start))

    subdivided.sort(key=lambda x: (x[1], x[0]))

    # 3. Match each tweet to the last block whose start <= adjusted time
    #    Subtract tweet_lag_seconds to compensate for the typical delay
    #    between a play occurring and the team account posting about it.
    lag = timedelta(seconds=tweet_lag_seconds)
    block_tweets: dict[int, list[ScoredTweet]] = {bs[0]: [] for bs in subdivided}
    for tweet in scored_tweets:
        adjusted_time = tweet.posted_at - lag
        target: int | None = None
        for block_idx, window_start in subdivided:
            if adjusted_time >= window_start:
                target = block_idx
            else:
                break
        if target is not None:
            block_tweets[target].append(tweet)

    # 4. Per block, pick highest-scored tweet as display, rest as additional
    assignments = [
        BlockTweetAssignment(block_index=i, tweet=None)
        for i in range(len(blocks))
    ]
    for block_idx, tweets in block_tweets.items():
        if not tweets:
            continue
        ranked = sorted(tweets, key=lambda t: t.score, reverse=True)
        assignments[block_idx] = BlockTweetAssignment(
            block_index=block_idx,
            tweet=ranked[0],
            additional_tweets=ranked[1:],
        )

    # 5. Enforce global cap: at most MAX_EMBEDDED_TWEETS blocks with display tweets
    display_blocks = [
        (a.block_index, a.tweet.score) for a in assignments if a.tweet is not None
    ]
    if len(display_blocks) > MAX_EMBEDDED_TWEETS:
        display_blocks.sort(key=lambda x: x[1], reverse=True)
        demoted_indices = {bi for bi, _ in display_blocks[MAX_EMBEDDED_TWEETS:]}
        for a in assignments:
            if a.block_index in demoted_indices and a.tweet is not None:
                a.additional_tweets.insert(0, a.tweet)
                a.tweet = None

    return assignments
