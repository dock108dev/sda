"""Polling tasks for game-state-machine architecture.

These tasks run at high frequency (3-5 min) and only touch games that
need attention right now, unlike the old batch sweeps that processed
everything for the last 96 hours.

The poll_live_pbp task handles:
- PBP polling for NBA/NHL (per-game)
- Boxscore polling for NBA/NHL live games (per-game)
- NCAAB PBP + boxscore polling (batch via CBB API)

Rate limit safeguards:
- Redis lock per task (prevents overlap from slow execution)
- 1-2s random jitter between API calls
- Max 30 API calls per PBP cycle, 20 per boxscore cycle
- 429 response → back off 60s, skip remaining games
"""

from __future__ import annotations

import random
import time

from celery import shared_task

from ..db import get_session
from ..logging import logger
from .polling_helpers import (
    _poll_mlb_game_boxscore,
    _poll_nba_game_boxscore,
    _poll_nhl_game_boxscore,
    _poll_single_game_pbp,
    _RateLimitError,
)
from .polling_helpers_ncaab import _poll_ncaab_games_batch

# Maximum API calls per polling cycle to stay within rate limits
_MAX_PBP_CALLS_PER_CYCLE = 30
_MAX_BOXSCORE_CALLS_PER_CYCLE = 20

# Jitter between API calls (seconds)
_JITTER_MIN = 1.0
_JITTER_MAX = 2.0

# Backoff on 429 responses
_RATE_LIMIT_BACKOFF_SECONDS = 60


from ..utils.redis_lock import LOCK_TIMEOUT_5MIN  # noqa: E402
from ..utils.redis_lock import acquire_redis_lock as _acquire_redis_lock  # noqa: E402
from ..utils.redis_lock import release_redis_lock as _release_redis_lock  # noqa: E402


def _dispatch_final_actions(game_id: int, league_code: str = "") -> None:
    """Dispatch social scrape, flow generation, and closing line capture for a game that just went final."""
    # Ensure closing lines are captured (idempotent — skips if already captured)
    try:
        from ..live_odds.closing_lines import capture_closing_lines
        capture_closing_lines(game_id, league_code)
    except Exception as exc:
        logger.warning("closing_lines_capture_error", game_id=game_id, error=str(exc))

    try:
        from .flow_trigger_tasks import trigger_flow_for_game

        trigger_flow_for_game.apply_async(
            args=[game_id],
            countdown=3600,
        )
        logger.info("flow_trigger_dispatched", game_id=game_id, countdown=3600)
    except Exception as exc:
        logger.warning("flow_trigger_dispatch_error", game_id=game_id, error=str(exc))

    if league_code == "MLB":
        try:
            from .mlb_advanced_stats_tasks import ingest_mlb_advanced_stats

            ingest_mlb_advanced_stats.apply_async(args=[game_id], countdown=60)
            logger.info("mlb_advanced_stats_dispatched", game_id=game_id)
        except Exception as exc:
            logger.warning("mlb_advanced_stats_dispatch_error", game_id=game_id, error=str(exc))


@shared_task(name="update_game_states")
def update_game_states_task() -> dict:
    """Promote games through lifecycle states (runs every 3 min).

    Pure DB — no external API calls. Handles:
    - scheduled → pregame (within pregame_window_hours of game_date)
    - final → archived (>7 days with timeline artifacts)
    """
    from ..services.game_state_updater import update_game_states
    from ..services.job_runs import complete_job_run, start_job_run

    lock_token = _acquire_redis_lock("lock:update_game_states", timeout=180)
    if not lock_token:
        logger.debug("update_game_states_skipped_locked")
        return {"skipped": True, "reason": "locked"}

    job_run_id = start_job_run("update_game_states", [])
    try:
        with get_session() as session:
            counts = update_game_states(session)
        complete_job_run(job_run_id, status="success", summary_data=counts)
        return counts
    except Exception as exc:
        complete_job_run(job_run_id, status="error", error_summary=str(exc)[:500])
        raise
    finally:
        _release_redis_lock("lock:update_game_states", lock_token)


@shared_task(name="poll_live_pbp")
def poll_live_pbp_task() -> dict:
    """Poll PBP, boxscores, and status for pregame/live games (runs every 5 min).

    Phases:
    1. NBA/NHL PBP polling (existing — per-game scoreboard + PBP fetch)
    2. NBA/NHL boxscore polling for live games (per-game fetch)
    3. NCAAB batch polling (PBP per-game + boxscores via batch endpoint)
    """
    from ..services.active_games import ActiveGamesResolver
    from ..services.job_runs import complete_job_run, start_job_run

    lock_token = _acquire_redis_lock("lock:poll_live_pbp", timeout=LOCK_TIMEOUT_5MIN)
    if not lock_token:
        logger.debug("poll_live_pbp_skipped_locked")
        return {"skipped": True, "reason": "locked"}

    job_run_id = start_job_run("poll_live_pbp", [])
    try:
        resolver = ActiveGamesResolver()

        with get_session() as session:
            # --- Phase 1: NBA/NHL PBP polling (existing) ---
            pbp_games = resolver.get_games_needing_pbp(session)

            api_calls = 0
            games_polled = 0
            transitions: list[dict] = []
            pbp_updated = 0
            rate_limited = False

            # Build league lookup and separate NCAAB from NBA/NHL/MLB
            from ..db import db_models

            league_map: dict[int, str] = {}
            nba_nhl_pbp_games: list = []
            ncaab_pbp_games: list = []
            if pbp_games:
                league_ids = {g.league_id for g in pbp_games}
                leagues = (
                    session.query(db_models.SportsLeague)
                    .filter(db_models.SportsLeague.id.in_(league_ids))
                    .all()
                )
                league_map = {lg.id: lg.code for lg in leagues}

            for game in pbp_games:
                code = league_map.get(game.league_id, "")
                if code == "NCAAB":
                    ncaab_pbp_games.append(game)
                else:
                    nba_nhl_pbp_games.append(game)

            # --- Phase 0: Populate missing external IDs (all leagues) ---
            if pbp_games:
                from ..services.mlb_boxscore_ingestion import populate_mlb_game_ids
                from ..services.ncaab_game_ids import populate_ncaab_game_ids
                from ..services.pbp_nba import populate_nba_game_ids
                from ..services.pbp_nhl import populate_nhl_game_ids

                game_dates = [g.game_date.date() for g in pbp_games if g.game_date]
                if game_dates:
                    start = min(game_dates)
                    end = max(game_dates)

                    try:
                        populate_nba_game_ids(session, start_date=start, end_date=end)
                    except Exception as exc:
                        logger.warning("poll_populate_nba_ids_error", error=str(exc))

                    try:
                        populate_nhl_game_ids(session, start_date=start, end_date=end)
                    except Exception as exc:
                        logger.warning("poll_populate_nhl_ids_error", error=str(exc))

                    try:
                        populate_mlb_game_ids(session, start_date=start, end_date=end)
                    except Exception as exc:
                        logger.warning("poll_populate_mlb_ids_error", error=str(exc))

                    try:
                        populate_ncaab_game_ids(session, start_date=start, end_date=end)
                    except Exception as exc:
                        logger.warning("poll_populate_ncaab_ids_error", error=str(exc))

                    # Refresh game objects to pick up newly-set external_ids
                    for game in pbp_games:
                        session.refresh(game)

            if not nba_nhl_pbp_games and not ncaab_pbp_games:
                logger.info(
                    "poll_live_pbp_heartbeat",
                    games_found=0,
                )
            else:
                logger.info(
                    "poll_live_data_start",
                    nba_nhl_pbp=len(nba_nhl_pbp_games),
                    ncaab_pbp=len(ncaab_pbp_games),
                )

            # NBA/NHL PBP loop (unchanged logic)
            for game in nba_nhl_pbp_games:
                if api_calls >= _MAX_PBP_CALLS_PER_CYCLE:
                    logger.info("poll_live_pbp_max_calls_reached", api_calls=api_calls)
                    break

                if rate_limited:
                    break

                if api_calls > 0:
                    time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

                try:
                    result = _poll_single_game_pbp(session, game)
                    api_calls += result.get("api_calls", 1)
                    games_polled += 1

                    if result.get("transition"):
                        transitions.append(result["transition"])
                        if result["transition"]["to"] == "final":
                            _dispatch_final_actions(
                                result["transition"]["game_id"],
                                league_code=league_map.get(game.league_id, ""),
                            )
                    if result.get("pbp_events", 0) > 0:
                        pbp_updated += 1

                except _RateLimitError:
                    logger.warning(
                        "poll_live_pbp_rate_limited",
                        game_id=game.id,
                        api_calls_so_far=api_calls,
                    )
                    rate_limited = True
                    time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)

                except Exception as exc:
                    logger.warning(
                        "poll_live_pbp_game_error",
                        game_id=game.id,
                        error=str(exc),
                    )
                    continue

            # --- Phase 2: NBA/NHL boxscore polling for live games ---
            boxscore_calls = 0
            boxscores_updated = 0

            if not rate_limited:
                boxscore_games = resolver.get_games_needing_boxscore(session)
                # Filter to NBA/NHL/MLB (NCAAB boxscores handled in batch phase)
                nba_nhl_box_games = [
                    g
                    for g in boxscore_games
                    if league_map.get(g.league_id, "") in ("NBA", "NHL", "MLB")
                ]
                # Ensure league_map covers boxscore games too
                if boxscore_games:
                    new_league_ids = {g.league_id for g in boxscore_games} - set(league_map.keys())
                    if new_league_ids:
                        extra = (
                            session.query(db_models.SportsLeague)
                            .filter(db_models.SportsLeague.id.in_(new_league_ids))
                            .all()
                        )
                        league_map.update({lg.id: lg.code for lg in extra})
                    nba_nhl_box_games = [
                        g
                        for g in boxscore_games
                        if league_map.get(g.league_id, "") in ("NBA", "NHL", "MLB")
                    ]

                for game in nba_nhl_box_games:
                    if boxscore_calls >= _MAX_BOXSCORE_CALLS_PER_CYCLE:
                        logger.info("poll_boxscore_max_calls_reached", calls=boxscore_calls)
                        break
                    if rate_limited:
                        break

                    if boxscore_calls > 0 or api_calls > 0:
                        time.sleep(random.uniform(_JITTER_MIN, _JITTER_MAX))

                    try:
                        code = league_map.get(game.league_id, "")
                        if code == "NBA":
                            bc_result = _poll_nba_game_boxscore(session, game)
                        elif code == "NHL":
                            bc_result = _poll_nhl_game_boxscore(session, game)
                        elif code == "MLB":
                            bc_result = _poll_mlb_game_boxscore(session, game)
                        else:
                            continue

                        boxscore_calls += bc_result.get("api_calls", 0)
                        if bc_result.get("boxscore_updated"):
                            boxscores_updated += 1

                    except _RateLimitError:
                        logger.warning(
                            "poll_boxscore_rate_limited",
                            game_id=game.id,
                            calls_so_far=boxscore_calls,
                        )
                        rate_limited = True
                        time.sleep(_RATE_LIMIT_BACKOFF_SECONDS)

                    except Exception as exc:
                        logger.warning(
                            "poll_boxscore_game_error",
                            game_id=game.id,
                            error=str(exc),
                        )
                        continue

            # --- Phase 3: NCAAB batch polling (PBP + boxscores) ---
            ncaab_stats: dict = {}
            if ncaab_pbp_games and not rate_limited:
                try:
                    ncaab_stats = _poll_ncaab_games_batch(session, ncaab_pbp_games)
                    api_calls += ncaab_stats.get("api_calls", 0)
                    pbp_updated += ncaab_stats.get("pbp_updated", 0)
                    boxscores_updated += ncaab_stats.get("boxscores_updated", 0)
                    transitions.extend(ncaab_stats.get("transitions", []))

                    # Dispatch final-whistle social + flow for NCAAB games that went final
                    for tr in ncaab_stats.get("transitions", []):
                        if tr["to"] == "final":
                            _dispatch_final_actions(tr["game_id"], league_code="NCAAB")

                except _RateLimitError:
                    logger.warning("poll_ncaab_rate_limited")
                    rate_limited = True
                except Exception as exc:
                    logger.warning("poll_ncaab_batch_error", error=str(exc))

            total_api_calls = api_calls + boxscore_calls

            logger.info(
                "poll_live_data_complete",
                games_polled=games_polled,
                api_calls=total_api_calls,
                transitions=len(transitions),
                pbp_updated=pbp_updated,
                boxscores_updated=boxscores_updated,
                ncaab_games=len(ncaab_pbp_games),
                rate_limited=rate_limited,
            )

            result = {
                "games_polled": games_polled,
                "api_calls": total_api_calls,
                "transitions": transitions,
                "pbp_updated": pbp_updated,
                "boxscores_updated": boxscores_updated,
                "rate_limited": rate_limited,
            }
            summary = {k: v for k, v in result.items() if k != "transitions"}
            summary["transitions"] = len(transitions)
            complete_job_run(job_run_id, status="success", summary_data=summary)
            return result

    except Exception as exc:
        complete_job_run(job_run_id, status="error", error_summary=str(exc)[:500])
        raise
    finally:
        _release_redis_lock("lock:poll_live_pbp", lock_token)
