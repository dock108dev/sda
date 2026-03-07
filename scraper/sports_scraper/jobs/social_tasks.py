"""Celery tasks for social collection.

These tasks run on the dedicated social-scraper worker for consistent IP/session.

Tasks:
- collect_social_for_league: Manual social collection triggered from admin UI / API
- collect_team_social: Scrape tweets for teams in a date range
- map_social_to_games: Assign unmapped tweets to games
"""

from __future__ import annotations

from datetime import date

from celery import shared_task

from ..celery_app import SOCIAL_BULK_QUEUE, SOCIAL_QUEUE
from ..config import settings
from ..logging import logger


def _report_social_completion(
    scrape_run_id: int | None,
    result: dict | None,
    error: str | None,
) -> None:
    """Update the SportsScrapeRun summary with actual social stats.

    Replaces the "Social: dispatched to worker" placeholder text with
    real tweet counts. Called from collect_team_social on the social-scraper
    worker after collection finishes.

    All DB work is wrapped in try/except so reporting failures never crash the task.
    """
    try:
        from ..db import db_models, get_session

        # Build the replacement summary string
        if error:
            social_summary = f"Social: error ({error[:80]})"
        elif result:
            tweets = result.get("total_new_tweets", 0)
            mapped = result.get("mapping", {}).get("mapped", 0)
            social_summary = f"Social: {tweets} tweets ({mapped} mapped)"
        else:
            social_summary = "Social: 0 tweets (0 mapped)"

        # Update the SportsScrapeRun summary (replace placeholder)
        if scrape_run_id is not None:
            with get_session() as session:
                run = (
                    session.query(db_models.SportsScrapeRun)
                    .filter(db_models.SportsScrapeRun.id == scrape_run_id)
                    .first()
                )
                if run and run.summary and "Social: dispatched to worker" in run.summary:
                    run.summary = run.summary.replace(
                        "Social: dispatched to worker", social_summary
                    )
                    logger.info(
                        "social_completion_reported",
                        scrape_run_id=scrape_run_id,
                        social_summary=social_summary,
                    )
    except Exception as exc:
        logger.warning(
            "social_completion_report_failed",
            scrape_run_id=scrape_run_id,
            error=str(exc),
        )


@shared_task(name="handle_social_task_failure")
def handle_social_task_failure(
    task_id: str,
    scrape_run_id: int | None = None,
) -> None:
    """Celery link_error callback for collect_team_social failures.

    Called automatically when collect_team_social fails after all retries.
    Celery passes the failed task's ID as the first positional argument,
    followed by the args bound via `.s()`.

    Updates the SportsScrapeRun summary with the error message.
    (SportsJobRun tracking is handled inside collect_team_social itself.)
    """
    from celery.result import AsyncResult

    # Retrieve the exception from the failed task's result backend
    result = AsyncResult(task_id)
    error_msg = str(result.result) if result.result else "unknown error"

    logger.error(
        "social_task_failed_callback",
        task_id=task_id,
        scrape_run_id=scrape_run_id,
        error=error_msg,
    )
    _report_social_completion(scrape_run_id, result=None, error=error_msg)


@shared_task(
    name="collect_social_for_league",
    queue=SOCIAL_BULK_QUEUE,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def collect_social_for_league(league: str) -> dict:
    """Collect social posts for a league. Runs on social-bulk queue.

    Manual social collection triggered from admin UI / API. It runs asynchronously
    (fire-and-forget) so sports ingestion doesn't wait for social.

    Collects tweets for all teams that played yesterday or today, then
    maps unmapped tweets to games.

    Args:
        league: League code (NBA, NHL)

    Returns:
        Summary stats dict with social_posts and games_processed
    """
    from datetime import timedelta

    from ..db import get_session
    from ..services.job_runs import track_job_run
    from ..social.team_collector import TeamTweetCollector
    from ..social.tweet_mapper import map_unmapped_tweets
    from ..utils.datetime_utils import today_et

    logger.info("social_task_started", league=league)

    end_date = today_et()
    start_date = end_date - timedelta(days=1)

    with track_job_run("collect_social_for_league", [league]) as tracker:
        with get_session() as session, TeamTweetCollector() as collector:
            def _map_after_batch():
                map_unmapped_tweets(
                    session=session,
                    batch_size=settings.social_config.tweet_mapper_batch_size,
                )

            result = collector.collect_for_date_range(
                session=session,
                league_code=league,
                start_date=start_date,
                end_date=end_date,
                on_batch_commit=_map_after_batch,
            )

            # Final mapping pass
            session.flush()
            map_result = map_unmapped_tweets(session=session, batch_size=settings.social_config.tweet_mapper_batch_size)
            result["mapping"] = map_result

        tracker.summary_data = result

    logger.info("social_task_complete", league=league, **{
        k: v for k, v in result.items() if k != "mapping"
    })
    return result


@shared_task(
    name="collect_team_social",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def collect_team_social(
    league_code: str,
    start_date: str,
    end_date: str,
    scrape_run_id: int | None = None,
    job_run_id: int | None = None,
) -> dict:
    """
    Collect tweets for all teams in a league that played in the date range.

    Job run tracking happens here on the social-scraper worker (not at
    dispatch time on the main scraper) so the SportsJobRun accurately
    reflects actual execution state.

    Args:
        league_code: League code (NBA, NHL, NCAAB)
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        scrape_run_id: Optional parent SportsScrapeRun ID for summary update

    Returns:
        Summary stats dict
    """
    from ..db import get_session
    from ..services.job_runs import track_job_run
    from ..social.team_collector import TeamTweetCollector
    from ..social.tweet_mapper import map_unmapped_tweets
    from ..utils.redis_lock import acquire_redis_lock, release_redis_lock

    lock_name = f"lock:collect_team_social:{league_code}"
    lock_token = acquire_redis_lock(lock_name, timeout=7200)  # 2h
    if not lock_token:
        logger.info("collect_team_social_skipped_locked", league_code=league_code)
        return {"status": "skipped", "reason": "already_running"}

    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)

        # No clamping — honour the exact range the caller requested.
        # cap_social_date_range was destroying backfill ranges by clamping
        # to yesterday+today.

        logger.info(
            "collect_team_social_start",
            league_code=league_code,
            start_date=str(start),
            end_date=str(end),
            original_start=start_date,
            original_end=end_date,
        )

        with track_job_run("social", [league_code], job_run_id=job_run_id) as tracker:
            with get_session() as session, TeamTweetCollector() as collector:
                # Fix 4: Map tweets incrementally after each batch commit
                def _map_after_batch():
                    map_unmapped_tweets(
                        session=session,
                        batch_size=settings.social_config.tweet_mapper_batch_size,
                    )

                result = collector.collect_for_date_range(
                    session=session,
                    league_code=league_code,
                    start_date=start,
                    end_date=end,
                    on_batch_commit=_map_after_batch,
                )

                # Final mapping pass for any remaining unmapped tweets
                session.flush()
                map_result = map_unmapped_tweets(session=session, batch_size=settings.social_config.tweet_mapper_batch_size)
                result["mapping"] = map_result

            tracker.summary_data = result

        logger.info(
            "collect_team_social_complete",
            league_code=league_code,
            result=result,
        )

        # Update parent SportsScrapeRun summary (replace "dispatched" placeholder)
        _report_social_completion(scrape_run_id, result, error=None)

        # Queue one collect_game_social + map after this backfill so
        # newly collected tweets get mapped and today's games refreshed.
        # The singleton lock inside collect_game_social prevents overlap
        # if one is already running.
        try:
            collect_game_social.apply_async(
                queue=SOCIAL_QUEUE,
                countdown=10,  # small delay so lock from any prior run clears
            )
            logger.info("collect_team_social_chained_game_social", league_code=league_code)
        except Exception as exc:
            logger.warning("collect_team_social_chain_failed", error=str(exc))

        return result
    finally:
        release_redis_lock(lock_name, lock_token)


@shared_task(
    name="map_social_to_games",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def map_social_to_games(batch_size: int = 1000) -> dict:
    """
    Map all unmapped tweets to games.

    Tweets are mapped based on posted_at falling within game windows.

    Args:
        batch_size: Number of tweets to process per batch

    Returns:
        Summary stats dict with mapped, no_game counts
    """
    from ..db import get_session
    from ..services.job_runs import track_job_run
    from ..social.tweet_mapper import map_unmapped_tweets
    from ..utils.redis_lock import acquire_redis_lock, release_redis_lock

    lock_token = acquire_redis_lock("lock:map_social_to_games", timeout=300)
    if not lock_token:
        logger.info("map_social_to_games_skipped_locked")
        return {"status": "skipped", "reason": "already_running"}

    try:
        logger.info("map_social_to_games_start", batch_size=batch_size)

        with track_job_run("map_social_to_games") as tracker:
            with get_session() as session:
                result = map_unmapped_tweets(session=session, batch_size=batch_size)
            tracker.summary_data = result

        logger.info("map_social_to_games_complete", result=result)

        return result
    finally:
        release_redis_lock("lock:map_social_to_games", lock_token)


@shared_task(
    name="collect_game_social",
    queue=SOCIAL_QUEUE,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def collect_game_social() -> dict:
    """Collect social posts for games with odds but missing/stale social data.

    Singleton: if already running, new invocations return immediately.
    Runs every 60 min via beat. Targets:
    1. Games (today + yesterday) with odds but NO social data yet
    2. Pregame/live games with stale social data (>2h since last scrape)

    Returns:
        Summary stats dict with teams_processed, total_new_tweets, errors
    """
    import random
    import time
    from datetime import timedelta

    from ..db import db_models, get_session
    from ..services.job_runs import track_job_run
    from ..social.team_collector import TeamTweetCollector
    from ..social.tweet_mapper import map_unmapped_tweets
    from ..utils.datetime_utils import (
        ET,
        end_of_et_day_utc,
        now_utc,
        start_of_et_day_utc,
        today_et,
    )
    from ..utils.redis_lock import acquire_redis_lock, release_redis_lock

    lock_token = acquire_redis_lock("lock:collect_game_social", timeout=3600)  # 1h
    if not lock_token:
        logger.info("collect_game_social_skipped_locked")
        return {"status": "skipped", "reason": "already_running"}

    try:
        game_date = today_et()
        yesterday = game_date - timedelta(days=1)
        utc_now = now_utc()
        stale_cutoff = utc_now - timedelta(hours=2)

        # Use proper UTC datetime bounds for timestamptz comparisons
        window_start = start_of_et_day_utc(yesterday)
        window_end = end_of_et_day_utc(game_date)

        logger.info("collect_game_social_start", game_date=str(game_date))

        with track_job_run("collect_game_social") as tracker, get_session() as session:
            active_statuses = [
                db_models.GameStatus.scheduled.value,
                db_models.GameStatus.pregame.value,
                db_models.GameStatus.live.value,
                db_models.GameStatus.final.value,
            ]

            # Query 1: games with odds but NO social data (today + yesterday)
            no_social_games = (
                session.query(db_models.SportsGame)
                .filter(
                    db_models.SportsGame.game_date >= window_start,
                    db_models.SportsGame.game_date < window_end,
                    db_models.SportsGame.last_odds_at.isnot(None),
                    db_models.SportsGame.last_social_at.is_(None),
                    db_models.SportsGame.status.in_(active_statuses),
                )
                .all()
            )

            # Query 2: games with stale social data (>2h since last scrape)
            # Includes pregame, live, AND final — postgame tweets matter too
            stale_games = (
                session.query(db_models.SportsGame)
                .filter(
                    db_models.SportsGame.game_date >= window_start,
                    db_models.SportsGame.game_date < window_end,
                    db_models.SportsGame.last_odds_at.isnot(None),
                    db_models.SportsGame.last_social_at < stale_cutoff,
                    db_models.SportsGame.status.in_(active_statuses),
                )
                .all()
            )

            # Deduplicate by game ID
            games = list({g.id: g for g in (no_social_games + stale_games)}.values())

            if not games:
                logger.info("collect_game_social_no_games", game_date=str(game_date))
                map_result = map_unmapped_tweets(session=session, batch_size=settings.social_config.tweet_mapper_batch_size)
                return {
                    "game_date": str(game_date),
                    "teams_processed": 0,
                    "total_new_tweets": 0,
                    "mapped": map_result.get("mapped", 0),
                }

            logger.info(
                "collect_game_social_found",
                game_date=str(game_date),
                games=len(games),
                no_social=len(no_social_games),
                stale=len(stale_games),
            )

            try:
                collector = TeamTweetCollector()
            except RuntimeError as exc:
                logger.error("collect_game_social_collector_unavailable", error=str(exc))
                return {
                    "game_date": str(game_date),
                    "teams_processed": 0,
                    "total_new_tweets": 0,
                    "error": str(exc),
                }

            social_cfg = settings.social_config

            total_new = 0
            teams_processed = 0
            errors = 0
            games_completed = 0
            game_new_tweets = 0
            scraped_team_ids: set[int] = set()

            for i, game in enumerate(games):
                # Inter-game cooldown — skip before the first game.
                # Use shorter delay when previous game had no new tweets.
                if i > 0:
                    if game_new_tweets == 0:
                        delay = social_cfg.early_exit_delay_seconds
                    else:
                        delay = random.uniform(
                            social_cfg.inter_game_delay_seconds,
                            social_cfg.inter_game_delay_max_seconds,
                        )
                    time.sleep(delay)

                game_new_tweets = 0
                game_errors = 0
                for team_id in (game.home_team_id, game.away_team_id):
                    if team_id in scraped_team_ids:
                        continue
                    scraped_team_ids.add(team_id)

                    try:
                        sports_day = game.game_date.astimezone(ET).date()
                        new_tweets = collector.collect_team_tweets(
                            session=session,
                            team_id=team_id,
                            start_date=sports_day,
                            end_date=sports_day,
                        )
                        total_new += new_tweets
                        game_new_tweets += new_tweets
                        teams_processed += 1
                        logger.info(
                            "collect_game_social_team_done",
                            team_id=team_id,
                            new_tweets=new_tweets,
                        )
                    except Exception as exc:
                        errors += 1
                        game_errors += 1
                        logger.warning(
                            "collect_game_social_team_error",
                            team_id=team_id,
                            error=str(exc),
                        )

                # Only stamp last_social_at when at least one team produced
                # tweets OR both teams completed without errors.  When
                # Playwright is broken every team silently returns 0 and
                # stamping would mark the game "fresh", hiding the failure
                # for 2 hours.
                if game_new_tweets > 0 or game_errors == 0:
                    game.last_social_at = utc_now

                games_completed += 1
                if games_completed % social_cfg.game_batch_size == 0:
                    session.commit()
                    logger.info(
                        "collect_game_social_batch_committed",
                        games_processed=games_completed,
                        total_new=total_new,
                    )

            # Shut down browser before mapping (no more scrapes needed)
            collector.close()

            # Final commit for remaining games (< batch size)
            session.commit()

            # Map newly collected tweets to games
            map_result = map_unmapped_tweets(session=session, batch_size=settings.social_config.tweet_mapper_batch_size)

            result = {
                "game_date": str(game_date),
                "teams_processed": teams_processed,
                "total_new_tweets": total_new,
                "mapped": map_result.get("mapped", 0),
                "errors": errors,
            }
            tracker.summary_data = result

        logger.info("collect_game_social_complete", **result)

        return result
    finally:
        release_redis_lock("lock:collect_game_social", lock_token)


