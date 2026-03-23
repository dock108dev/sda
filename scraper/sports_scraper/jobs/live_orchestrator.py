"""Dynamic live-game orchestrator.

Runs every 5 seconds. Discovers live games by league and dispatches
per-game polling tasks at sport-appropriate cadences with jitter.

Scheduling keys tracked in Redis:
  sched:pbp:{league}:{game_id}
  sched:stats:{league}:{game_id}
  sched:odds:mainline:{league}:{game_id}
  sched:odds:props:{league}:{game_id}
"""

from __future__ import annotations

import random
import time

from celery import shared_task

from ..celery_app import DEFAULT_QUEUE
from ..db import db_models, get_session
from ..logging import logger
from ..utils.redis_lock import LOCK_TIMEOUT_5MIN, acquire_redis_lock, release_redis_lock

# ---------------------------------------------------------------------------
# Cadence configs (seconds) — live odds only.
# PBP/stats polling is handled by the Beat-scheduled poll_live_pbp_task.
# ---------------------------------------------------------------------------

ODDS_MAINLINE_CADENCE = 15   # All leagues
ODDS_PROPS_CADENCE = 45      # All leagues

# Jitter range (fraction of cadence)
JITTER_FRACTION = 0.2

# Orchestrator tick interval — Beat fires every 5 seconds
TICK_INTERVAL_S = 5


def _sched_key(category: str, league: str, game_id: int) -> str:
    return f"sched:{category}:{league}:{game_id}"


def _is_due(r, key: str, cadence_s: float) -> bool:
    """Check if a scheduling key is due (elapsed >= cadence)."""
    last = r.get(key)
    if last is None:
        return True
    try:
        elapsed = time.time() - float(last)
        return elapsed >= cadence_s
    except (ValueError, TypeError):
        return True


def _mark_scheduled(r, key: str) -> None:
    """Mark a scheduling key as just-fired with 1-hour TTL."""
    r.set(key, str(time.time()), ex=3600)


def _jitter(cadence: float) -> float:
    """Add random jitter to a cadence value."""
    return cadence + random.uniform(0, cadence * JITTER_FRACTION)


@shared_task(name="live_orchestrator_tick")
def live_orchestrator_tick() -> dict:
    """Discover live games and dispatch per-game tasks at appropriate cadences."""
    import redis as redis_lib

    from ..config import settings

    lock_token = acquire_redis_lock("lock:live_orchestrator", timeout=LOCK_TIMEOUT_5MIN)
    if not lock_token:
        return {"skipped": True, "reason": "locked"}

    try:
        r = redis_lib.from_url(settings.redis_url, decode_responses=True)

        with get_session() as session:
            # Only poll live odds for games actually in progress.
            # Pregame odds are handled by the Beat-scheduled sync_mainline_odds
            # task.  Including pregame here would write pregame lines into the
            # live Redis keys and pollute the live odds view.
            live_games = (
                session.query(
                    db_models.SportsGame.id,
                    db_models.SportsGame.status,
                    db_models.SportsLeague.code,
                )
                .join(db_models.SportsLeague)
                .filter(
                    db_models.SportsGame.status == "live",
                )
                .all()
            )

        if not live_games:
            return {"live_games": 0, "dispatched": 0}

        dispatched = 0
        games_by_league: dict[str, list[int]] = {}

        for game_id, _status, league_code in live_games:
            games_by_league.setdefault(league_code, []).append(game_id)

            # PBP and boxscore polling are handled by the Beat-scheduled
            # poll_live_pbp_task (every 60s). The orchestrator only manages
            # live odds dispatch, which requires sport-specific cadences.

        # --- Live odds (league-batched) ---
        for league_code, game_ids in games_by_league.items():
            ml_key = _sched_key("odds:mainline", league_code, 0)
            if _is_due(r, ml_key, _jitter(ODDS_MAINLINE_CADENCE)):
                _mark_scheduled(r, ml_key)
                try:
                    from .live_odds_tasks import poll_live_odds_mainline
                    poll_live_odds_mainline.apply_async(
                        args=[league_code, game_ids],
                        queue=DEFAULT_QUEUE,
                    )
                    dispatched += 1
                except Exception as exc:
                    logger.warning("orchestrator_dispatch_odds_error", error=str(exc))

            props_key = _sched_key("odds:props", league_code, 0)
            if _is_due(r, props_key, _jitter(ODDS_PROPS_CADENCE)):
                _mark_scheduled(r, props_key)
                try:
                    from .live_odds_tasks import poll_live_odds_props
                    poll_live_odds_props.apply_async(
                        args=[league_code, game_ids],
                        queue=DEFAULT_QUEUE,
                    )
                    dispatched += 1
                except Exception as exc:
                    logger.warning("orchestrator_dispatch_props_error", error=str(exc))

        logger.info(
            "live_orchestrator_tick_complete",
            live_games=len(live_games),
            leagues=list(games_by_league.keys()),
            dispatched=dispatched,
        )

        return {
            "live_games": len(live_games),
            "dispatched": dispatched,
            "leagues": {k: len(v) for k, v in games_by_league.items()},
        }

    finally:
        release_redis_lock("lock:live_orchestrator", lock_token)
