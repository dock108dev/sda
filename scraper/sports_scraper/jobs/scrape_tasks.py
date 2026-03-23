"""Celery tasks for scrape job execution."""

from __future__ import annotations

from datetime import UTC

from celery import shared_task

from ..logging import logger
from ..services.ingestion import run_ingestion


def _append_pbp_to_run_summary(run_id: int | None, pbp_games: int) -> None:
    """Append PBP counts to an existing run's summary string."""
    if not run_id or not pbp_games:
        return
    from ..db import db_models, get_session
    try:
        with get_session() as session:
            run = session.query(db_models.SportsScrapeRun).filter_by(id=run_id).first()
            if run and run.summary:
                run.summary = f"{run.summary}, PBP: {pbp_games}"
    except Exception as exc:
        logger.warning("pbp_summary_append_failed", run_id=run_id, error=str(exc))


@shared_task(name="run_scrape_job")
def run_scrape_job(run_id: int, config_payload: dict) -> dict:
    """Run a scrape job (data ingestion only).

    Timeline/flow generation is decoupled — use the per-league flow
    generation tasks or Pipeline API endpoints for manual control.
    """
    from ..services.job_runs import complete_job_run
    from ..utils.datetime_utils import now_utc
    from ..utils.redis_lock import (
        LOCK_TIMEOUT_1HOUR,
        acquire_redis_lock,
        force_release_lock,
        release_redis_lock,
    )

    league_code = config_payload.get("league_code", "UNKNOWN")
    lock_name = f"lock:ingest:{league_code}"

    # Find and activate any queued job run for this Celery task
    task_id = run_scrape_job.request.id
    job_run_id = _activate_job_run_for_task(task_id)

    # Try to acquire the lock. If it fails, force-release and retry —
    # the previous lock may be orphaned from a crashed worker.
    lock_token = acquire_redis_lock(lock_name, timeout=LOCK_TIMEOUT_1HOUR)
    if not lock_token:
        import time
        logger.info("scrape_job_lock_retry", run_id=run_id, league=league_code)
        time.sleep(5)
        force_release_lock(lock_name)
        lock_token = acquire_redis_lock(lock_name, timeout=LOCK_TIMEOUT_1HOUR)

    if not lock_token:
        logger.warning("scrape_job_skipped_locked", run_id=run_id, league=league_code)
        from ..services.run_manager import ScrapeRunManager
        mgr = ScrapeRunManager()
        mgr._update_run(
            run_id,
            status="skipped",
            summary="Skipped: ingestion already in progress for this league",
            finished_at=now_utc(),
        )
        if job_run_id:
            complete_job_run(job_run_id, "skipped", "Ingestion already in progress")
        return {"status": "skipped", "reason": "ingestion_in_progress", "run_id": run_id}

    try:
        logger.info("scrape_job_started", run_id=run_id)
        result = run_ingestion(run_id, config_payload)
        logger.info("scrape_job_completed", run_id=run_id, result=result)
        if job_run_id:
            complete_job_run(job_run_id, "success", summary_data=result)
        return result
    except Exception as exc:
        if job_run_id:
            complete_job_run(job_run_id, "error", str(exc)[:500])
        raise
    finally:
        release_redis_lock(lock_name, lock_token)


def _activate_job_run_for_task(celery_task_id: str | None) -> int | None:
    """Find a queued SportsJobRun by celery_task_id and activate it."""
    if not celery_task_id:
        return None
    try:
        from ..db import db_models, get_session
        from ..services.job_runs import activate_queued_job_run

        with get_session() as session:
            run = (
                session.query(db_models.SportsJobRun)
                .filter(
                    db_models.SportsJobRun.celery_task_id == celery_task_id,
                    db_models.SportsJobRun.status == "queued",
                )
                .first()
            )
            if not run:
                return None
            job_run_id = int(run.id)

        return activate_queued_job_run(job_run_id)
    except Exception as exc:
        logger.warning("job_run_activation_failed", celery_task_id=celery_task_id, error=str(exc))
        return None


@shared_task(
    name="run_scheduled_ingestion",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_scheduled_ingestion() -> dict:
    """Trigger the scheduled ingestion pipeline.

    Runs leagues sequentially with PBP after each:
    1. NBA stats → PBP
    2. NHL stats → PBP
    3. NCAAB stats → PBP

    Social collection is dispatched asynchronously to the dedicated
    social-scraper worker after each league's PBP completes.
    This is fire-and-forget - we don't wait for social to complete.
    """
    from ..services.job_runs import track_job_run
    from ..services.scheduler import (
        run_pbp_ingestion_for_league,
        schedule_single_league_and_wait,
    )

    leagues = ["NBA", "NHL", "NCAAB", "MLB", "NFL"]

    with track_job_run("scheduled_ingestion", leagues) as tracker:
        results = {}

        # === NBA ===
        logger.info("scheduled_ingestion_nba_start")
        nba_result = schedule_single_league_and_wait("NBA")
        results["NBA"] = nba_result
        logger.info("scheduled_ingestion_nba_complete", **nba_result)

        logger.info("scheduled_ingestion_nba_pbp_start")
        nba_pbp_result = run_pbp_ingestion_for_league("NBA")
        results["NBA_PBP"] = nba_pbp_result
        _append_pbp_to_run_summary(nba_result.get("run_id"), nba_pbp_result.get("pbp_games", 0))
        logger.info("scheduled_ingestion_nba_pbp_complete", **nba_pbp_result)

        # === NHL ===
        logger.info("scheduled_ingestion_nhl_start")
        nhl_result = schedule_single_league_and_wait("NHL")
        results["NHL"] = nhl_result
        logger.info("scheduled_ingestion_nhl_complete", **nhl_result)

        logger.info("scheduled_ingestion_nhl_pbp_start")
        nhl_pbp_result = run_pbp_ingestion_for_league("NHL")
        results["NHL_PBP"] = nhl_pbp_result
        _append_pbp_to_run_summary(nhl_result.get("run_id"), nhl_pbp_result.get("pbp_games", 0))
        logger.info("scheduled_ingestion_nhl_pbp_complete", **nhl_pbp_result)

        # === NCAAB ===
        logger.info("scheduled_ingestion_ncaab_start")
        ncaab_result = schedule_single_league_and_wait("NCAAB")
        results["NCAAB"] = ncaab_result
        logger.info("scheduled_ingestion_ncaab_complete", **ncaab_result)

        logger.info("scheduled_ingestion_ncaab_pbp_start")
        ncaab_pbp_result = run_pbp_ingestion_for_league("NCAAB")
        results["NCAAB_PBP"] = ncaab_pbp_result
        _append_pbp_to_run_summary(ncaab_result.get("run_id"), ncaab_pbp_result.get("pbp_games", 0))
        logger.info("scheduled_ingestion_ncaab_pbp_complete", **ncaab_pbp_result)

        # === MLB ===
        logger.info("scheduled_ingestion_mlb_start")
        mlb_result = schedule_single_league_and_wait("MLB")
        results["MLB"] = mlb_result
        logger.info("scheduled_ingestion_mlb_complete", **mlb_result)

        logger.info("scheduled_ingestion_mlb_pbp_start")
        mlb_pbp_result = run_pbp_ingestion_for_league("MLB")
        results["MLB_PBP"] = mlb_pbp_result
        _append_pbp_to_run_summary(mlb_result.get("run_id"), mlb_pbp_result.get("pbp_games", 0))
        logger.info("scheduled_ingestion_mlb_pbp_complete", **mlb_pbp_result)

        # === NFL ===
        logger.info("scheduled_ingestion_nfl_start")
        nfl_result = schedule_single_league_and_wait("NFL")
        results["NFL"] = nfl_result
        logger.info("scheduled_ingestion_nfl_complete", **nfl_result)

        logger.info("scheduled_ingestion_nfl_pbp_start")
        nfl_pbp_result = run_pbp_ingestion_for_league("NFL")
        results["NFL_PBP"] = nfl_pbp_result
        _append_pbp_to_run_summary(nfl_result.get("run_id"), nfl_pbp_result.get("pbp_games", 0))
        logger.info("scheduled_ingestion_nfl_pbp_complete", **nfl_pbp_result)

        summary = {
            "leagues": results,
            "total_runs_created": nba_result["runs_created"] + nhl_result["runs_created"] + ncaab_result["runs_created"] + mlb_result["runs_created"] + nfl_result["runs_created"],
            "total_pbp_games": nba_pbp_result["pbp_games"] + nhl_pbp_result["pbp_games"] + ncaab_pbp_result["pbp_games"] + mlb_pbp_result["pbp_games"] + nfl_pbp_result["pbp_games"],
        }
        tracker.summary_data = summary

    return summary


_CALENDAR_LOOKAHEAD_DAYS = 7


@shared_task(name="poll_game_calendars")
def poll_game_calendars() -> dict:
    """Lightweight calendar poll that creates game stubs for all leagues.

    Looks 7 days ahead so upcoming games (including postseason matchups,
    schedule changes, and rain-delay reschedules) are in the DB well
    before tip-off.  Runs every 15 minutes.  Idempotent — existing
    games are not duplicated.
    """
    from datetime import datetime, timedelta

    from ..db import get_session
    from ..logging import logger
    from ..models import TeamIdentity
    from ..persistence.games import upsert_game_stub
    from ..utils.datetime_utils import sports_today_et

    today = sports_today_et()
    end_day = today + timedelta(days=_CALENDAR_LOOKAHEAD_DAYS)
    days = [today + timedelta(days=i) for i in range(_CALENDAR_LOOKAHEAD_DAYS)]

    results: dict[str, dict] = {}

    # --- NBA (scoreboard is per-day) ---
    try:
        from ..live.nba import NBALiveFeedClient

        client = NBALiveFeedClient()
        created = 0
        with get_session() as session:
            for day in days:
                for game in client.fetch_scoreboard(day):
                    try:
                        _gid, was_created = upsert_game_stub(
                            session,
                            league_code="NBA",
                            game_date=game.game_date,
                            home_team=TeamIdentity(name="", abbreviation=game.home_abbr),
                            away_team=TeamIdentity(name="", abbreviation=game.away_abbr),
                            status=game.status,
                            home_score=game.home_score,
                            away_score=game.away_score,
                        )
                        if was_created:
                            created += 1
                    except Exception as exc:
                        logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NBA"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_nba_failed", error=str(exc))
        results["NBA"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- NHL (schedule supports date range) ---
    try:
        from ..live.nhl import NHLLiveFeedClient

        client = NHLLiveFeedClient()
        created = 0
        with get_session() as session:
            for game in client.fetch_schedule(today, end_day):
                try:
                    _gid, was_created = upsert_game_stub(
                        session,
                        league_code="NHL",
                        game_date=game.game_date,
                        home_team=game.home_team,
                        away_team=game.away_team,
                        status=game.status,
                        home_score=game.home_score,
                        away_score=game.away_score,
                        external_ids={"nhl_game_id": str(game.game_id)},
                    )
                    if was_created:
                        created += 1
                except Exception as exc:
                    logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NHL"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_nhl_failed", error=str(exc))
        results["NHL"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- MLB (schedule supports date range) ---
    try:
        from ..services.mlb_boxscore_ingestion import populate_mlb_games_from_schedule

        with get_session() as session:
            created = populate_mlb_games_from_schedule(
                session, start_date=today, end_date=end_day,
            )
            session.commit()
        results["MLB"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_mlb_failed", error=str(exc))
        results["MLB"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- NCAAB (scoreboard is per-day; future dates may have limited data) ---
    try:
        import httpx

        from ..live.ncaa_scoreboard import NCAAScoreboardClient

        client = NCAAScoreboardClient(httpx.Client(timeout=20))
        created = 0
        with get_session() as session:
            for day in days:
                try:
                    scoreboard_games = client.fetch_scoreboard(day)
                except Exception:
                    continue  # NCAA API may not support all future dates
                for game in scoreboard_games:
                    try:
                        if game.start_time_epoch:
                            game_date = datetime.fromtimestamp(
                                game.start_time_epoch / 1000, tz=UTC,
                            )
                        else:
                            game_date = datetime.combine(
                                day, datetime.min.time(),
                            ).replace(hour=12, tzinfo=UTC)

                        _gid, was_created = upsert_game_stub(
                            session,
                            league_code="NCAAB",
                            game_date=game_date,
                            home_team=TeamIdentity(
                                name=game.home_team_short, abbreviation="",
                            ),
                            away_team=TeamIdentity(
                                name=game.away_team_short, abbreviation="",
                            ),
                            status=game.game_state,
                            home_score=game.home_score,
                            away_score=game.away_score,
                            external_ids={"ncaa_game_id": game.ncaa_game_id},
                        )
                        if was_created:
                            created += 1
                    except Exception as exc:
                        logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NCAAB"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_ncaab_failed", error=str(exc))
        results["NCAAB"] = {"created": 0, "status": "error", "error": str(exc)}

    # --- NFL (ESPN scoreboard, date range via per-day iteration) ---
    try:
        from ..live.nfl import NFLLiveFeedClient

        client = NFLLiveFeedClient()
        created = 0
        with get_session() as session:
            for game in client.fetch_schedule(today, end_day):
                try:
                    if game.season_type == "preseason":
                        continue
                    _gid, was_created = upsert_game_stub(
                        session,
                        league_code="NFL",
                        game_date=game.game_date,
                        home_team=game.home_team,
                        away_team=game.away_team,
                        status=game.status,
                        home_score=game.home_score,
                        away_score=game.away_score,
                        external_ids={"espn_game_id": game.game_id},
                        season_type=game.season_type or "regular",
                    )
                    if was_created:
                        created += 1
                except Exception as exc:
                    logger.debug("game_stub_error", error=str(exc))
            session.commit()
        results["NFL"] = {"created": created, "status": "ok"}
    except Exception as exc:
        logger.warning("calendar_poll_nfl_failed", error=str(exc))
        results["NFL"] = {"created": 0, "status": "error", "error": str(exc)}

    total_created = sum(r.get("created", 0) for r in results.values())
    logger.info(
        "calendar_poll_complete",
        total_created=total_created,
        results=results,
    )

    return {"total_created": total_created, "leagues": results}


@shared_task(name="ingest_nba_historical")
def ingest_nba_historical(start_date: str, end_date: str, boxscores: bool = True, pbp: bool = True) -> dict:
    """Backfill historical NBA data from Basketball Reference.

    Politely scrapes boxscores, player stats, and PBP for seasons
    where the NBA CDN API is no longer available. Uses 5-9 second
    delays between requests and caches HTML locally.

    Args:
        start_date: YYYY-MM-DD format
        end_date: YYYY-MM-DD format
        boxscores: Whether to backfill boxscores + player stats
        pbp: Whether to backfill play-by-play
    """
    from datetime import date as date_type

    from ..db import get_session
    from ..services.job_runs import complete_job_run, start_job_run
    from ..services.nba_historical_ingestion import (
        ingest_nba_historical_boxscores,
        ingest_nba_historical_pbp,
    )
    from ..utils.redis_lock import LOCK_TIMEOUT_1HOUR, acquire_redis_lock, release_redis_lock

    start = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date)
    lock_name = "lock:nba_historical"

    lock_token = acquire_redis_lock(lock_name, timeout=LOCK_TIMEOUT_1HOUR * 24)
    if not lock_token:
        logger.warning("nba_historical_skipped_locked")
        return {"status": "skipped", "reason": "already_running"}

    job_run_id = start_job_run("nba_historical", ["NBA"])
    results: dict = {}

    try:
        with get_session() as session:
            if boxscores:
                processed, enriched, with_stats = ingest_nba_historical_boxscores(
                    session, start_date=start, end_date=end,
                )
                results["boxscores"] = {
                    "processed": processed, "enriched": enriched, "with_stats": with_stats,
                }

            if pbp:
                pbp_count = ingest_nba_historical_pbp(
                    session, start_date=start, end_date=end,
                )
                results["pbp"] = {"processed": pbp_count}

        complete_job_run(job_run_id, "success", summary_data=results)
    except Exception as exc:
        complete_job_run(job_run_id, "error", str(exc)[:500])
        raise
    finally:
        release_redis_lock(lock_name, lock_token)

    return results

