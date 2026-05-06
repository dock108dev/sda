"""SSOT per-game processing functions for all leagues.

Each function takes a session + SportsGame ORM object, fetches data from the
shared API client, calls shared persistence functions, and returns a
GameProcessResult. Functions do NOT handle game selection, rate limiting,
jitter, or locking -- those are caller-side concerns.

Both the live polling path (polling_helpers.py) and the manual/scheduled
ingestion path (pbp_*.py, *_boxscore_ingestion.py) call these same functions,
ensuring identical processing regardless of trigger.

Per-league implementations live in game_processors_{league}.py modules.
This file provides the shared dataclass, helpers, dispatchers, and
public re-exports.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..logging import logger


@dataclass
class GameProcessResult:
    """Result of processing a single game."""

    api_calls: int = 0
    events_inserted: int = 0
    boxscore_updated: bool = False
    transition: dict | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def has_game_action(plays: list) -> bool:
    """Check whether any plays represent actual game action (period >= 1).

    Pre-game events (lineup announcements, status changes, etc.) have
    ``quarter=None`` or ``quarter=0``.  Only plays with ``quarter >= 1``
    indicate the game has started.  Used to guard the pregame → live
    status promotion so pre-game API events don't prematurely flip games
    to live status.
    """
    return any(
        getattr(p, "quarter", None) is not None and getattr(p, "quarter", 0) >= 1
        for p in plays
    )


def _get_redis_client():  # noqa: ANN202
    import redis as redis_lib

    from ..config import settings

    return redis_lib.from_url(settings.redis_url, decode_responses=True)


def _pbp_signature(plays: list) -> str:
    """Build a stable fingerprint for normalized PBP payloads."""
    rows = [
        {
            "play_index": getattr(play, "play_index", None),
            "event_id": getattr(play, "event_id", None),
            "quarter": getattr(play, "quarter", None),
            "game_clock": getattr(play, "game_clock", None),
            "play_type": getattr(play, "play_type", None),
            "team_abbreviation": getattr(play, "team_abbreviation", None),
            "player_id": getattr(play, "player_id", None),
            "description": getattr(play, "description", None),
            "home_score": getattr(play, "home_score", None),
            "away_score": getattr(play, "away_score", None),
        }
        for play in plays
    ]
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def live_pbp_payload_unchanged(league: str, game_id: int, plays: list) -> bool:
    """Return True when a live PBP payload matches the last observed payload.

    This is intentionally best-effort. If Redis is unavailable, callers should
    proceed with normal persistence so live data is not silently dropped.
    """
    if not plays:
        return False

    signature = _pbp_signature(plays)
    key = f"live:pbp_hash:{league}:{game_id}"
    # Narrow to RedisError + OSError (transport / connection refused). A
    # programming bug (TypeError, NameError) must surface — degrading the
    # dedupe to "always proceed" is fine, but doing so silently would hide
    # the real fault.
    try:
        import redis as redis_lib

        r = _get_redis_client()
        previous = r.get(key)
        r.set(key, signature, ex=6 * 60 * 60)
        if previous == signature:
            logger.debug(
                "live_pbp_payload_unchanged",
                league=league,
                game_id=game_id,
                play_count=len(plays),
            )
            return True
    except (redis_lib.RedisError, OSError):
        logger.debug(
            "live_pbp_hash_check_failed",
            league=league,
            game_id=game_id,
            exc_info=True,
        )
    return False


def should_create_live_pbp_snapshot(
    league: str,
    game_id: int,
    *,
    throttle_seconds: int = 60,
) -> bool:
    """Throttle raw PBP snapshots for high-frequency live polling."""
    key = f"live:pbp_snapshot:{league}:{game_id}"
    # See live_pbp_payload_unchanged above for rationale on the narrowed
    # catch. Snapshot throttle fails open (returns True → write the snapshot)
    # so a Redis outage does not cost us live data; programming bugs still
    # propagate.
    try:
        import redis as redis_lib

        r = _get_redis_client()
        return bool(r.set(key, "1", nx=True, ex=throttle_seconds))
    except (redis_lib.RedisError, OSError):
        logger.debug(
            "live_pbp_snapshot_throttle_failed",
            league=league,
            game_id=game_id,
            exc_info=True,
        )
        return True


def try_promote_to_live(
    game,
    plays: list,
    result: GameProcessResult,
    league: str,
    *,
    db_models=None,
    now_utc_fn=None,
) -> None:
    """Promote a pregame game to live if plays contain actual game action.

    Mutates ``game.status`` and populates ``result.transition`` if
    promotion occurs.  No-op if the game is not in pregame status or
    if the plays are only pre-game events.
    """
    if db_models is None:
        from ..db import db_models as _dbm
        db_models = _dbm
    if now_utc_fn is None:
        from ..utils.datetime_utils import now_utc
        now_utc_fn = now_utc

    if game.status != db_models.GameStatus.pregame.value:
        return
    if not has_game_action(plays):
        return

    # Defense-in-depth against synthetic/early plays from upstream feeds:
    # if scheduled tipoff is still in the future, no PBP signal can mean
    # the game is actually in progress. Refuse the promotion so a stray
    # API "advisory" event can't flip the game to live before kickoff.
    now = now_utc_fn()
    if game.game_date is not None and game.game_date > now:
        logger.info(
            "poll_pbp_inferred_live_blocked_future",
            game_id=game.id,
            league=league,
            game_date=str(game.game_date),
            now=str(now),
            play_count=len(plays),
        )
        return

    game.status = db_models.GameStatus.live.value
    game.updated_at = now
    result.transition = {
        "game_id": game.id,
        "from": "pregame",
        "to": "live",
    }
    logger.info(
        "poll_pbp_inferred_live",
        game_id=game.id,
        league=league,
        reason="pbp_game_action_found",
        play_count=len(plays),
    )


# ---------------------------------------------------------------------------
# Re-exports — canonical import path for all callers
# ---------------------------------------------------------------------------

from .game_processors_mlb import (  # noqa: E402, F401
    check_game_status_mlb,
    process_game_boxscore_mlb,
    process_game_pbp_mlb,
)
from .game_processors_nba import (  # noqa: E402, F401
    check_game_status_nba,
    process_game_boxscore_nba,
    process_game_pbp_nba,
)
from .game_processors_ncaab import (  # noqa: E402, F401
    process_game_boxscore_ncaab,
    process_game_boxscores_ncaab_batch,
    process_game_pbp_ncaab,
)
from .game_processors_nfl import (  # noqa: E402, F401
    check_game_status_nfl,
    process_game_boxscore_nfl,
    process_game_pbp_nfl,
)
from .game_processors_nhl import (  # noqa: E402, F401
    check_game_status_nhl,
    process_game_boxscore_nhl,
    process_game_pbp_nhl,
)

# ---------------------------------------------------------------------------
# Dispatchers (route by league_code)
# ---------------------------------------------------------------------------


def process_game_pbp(session, game, league_code: str) -> GameProcessResult:
    """Dispatch PBP processing to the appropriate league handler."""
    if league_code == "NBA":
        return process_game_pbp_nba(session, game)
    elif league_code == "NHL":
        return process_game_pbp_nhl(session, game)
    elif league_code == "MLB":
        return process_game_pbp_mlb(session, game)
    elif league_code == "NCAAB":
        return process_game_pbp_ncaab(session, game)
    elif league_code == "NFL":
        return process_game_pbp_nfl(session, game)
    return GameProcessResult()


def process_game_boxscore(session, game, league_code: str) -> GameProcessResult:
    """Dispatch boxscore processing to the appropriate league handler."""
    if league_code == "NBA":
        return process_game_boxscore_nba(session, game)
    elif league_code == "NHL":
        return process_game_boxscore_nhl(session, game)
    elif league_code == "MLB":
        return process_game_boxscore_mlb(session, game)
    elif league_code == "NCAAB":
        return process_game_boxscore_ncaab(session, game)
    elif league_code == "NFL":
        return process_game_boxscore_nfl(session, game)
    return GameProcessResult()
