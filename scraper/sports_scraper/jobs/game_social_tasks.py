"""Game-targeted social collection Celery task."""

from __future__ import annotations

from celery import shared_task

from ..celery_app import SOCIAL_QUEUE
from ..config import settings
from ..logging import logger


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
        end_of_et_day_utc,
        now_utc,
        start_of_et_day_utc,
        to_et_date,
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

            # Pre-load the set of team IDs that already have fresh posts
            # from a previous (committed) batch so we can skip the
            # Playwright call entirely on restart without holding a
            # transaction across each iteration. One short query up front
            # replaces a per-team check inside the IO-heavy loop.
            fresh_cutoff = utc_now - timedelta(hours=1)
            game_team_ids = {tid for g in games for tid in (g.home_team_id, g.away_team_id)}
            fresh_team_rows = (
                session.query(db_models.TeamSocialPost.team_id)
                .filter(
                    db_models.TeamSocialPost.team_id.in_(game_team_ids),
                    db_models.TeamSocialPost.created_at >= fresh_cutoff,
                )
                .distinct()
                .all()
            )
            fresh_team_ids: set[int] = {row[0] for row in fresh_team_rows}
            session.commit()  # release locks acquired by the pre-load query

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
                    # Commit any pending state from the previous iteration
                    # so we hold no lock across the wall-clock sleep.
                    session.commit()
                    time.sleep(delay)

                game_new_tweets = 0
                game_errors = 0
                for team_id in (game.home_team_id, game.away_team_id):
                    if team_id in scraped_team_ids:
                        continue
                    scraped_team_ids.add(team_id)

                    if team_id in fresh_team_ids:
                        logger.debug(
                            "collect_game_social_team_skip_fresh",
                            team_id=team_id,
                        )
                        teams_processed += 1
                        continue

                    try:
                        sports_day = to_et_date(game.game_date)
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

