"""Daily sweep task: truth repair and housekeeping.

Runs once daily (4 AM EST) as a safety net to catch anything the
high-frequency polling tasks missed. Responsibilities:

1. Status repair: find scheduled games past game_date, check API for actual status
2. Social: second-pass social scrape for postgame reactions
3. Embedded tweet backfill: attach tweets to flows generated before social completed
4. Archive: move final games >7 days with complete artifacts to archived

Note: Full pipeline re-runs and flow generation were removed — the 3:30 AM
ingestion (now using NBA CDN API for boxscores) and dedicated flow tasks
at 4:30/5:00/5:30 AM handle those responsibilities.
"""

from __future__ import annotations

from datetime import timedelta

from celery import shared_task

from ..config import settings
from ..db import get_session
from ..logging import logger


@shared_task(
    name="run_daily_sweep",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_daily_sweep() -> dict:
    """Run all daily sweep operations."""
    from ..services.job_runs import track_job_run

    results: dict = {}

    logger.info("daily_sweep_start")

    with track_job_run("daily_sweep") as tracker:
        # --- Phase 1: Pre-ingestion housekeeping ---
        try:
            results["status_repair"] = _repair_stale_statuses()
        except Exception as exc:
            results["status_repair"] = {"error": str(exc)}
            logger.exception("daily_sweep_status_repair_error", error=str(exc))

        # --- Phase 2: Post-ingestion housekeeping ---
        try:
            results["social_scrape_2"] = _run_social_scrape_2()
        except Exception as exc:
            results["social_scrape_2"] = {"error": str(exc)}
            logger.exception("daily_sweep_social_scrape_2_error", error=str(exc))

        try:
            results["embedded_tweets_backfill"] = _backfill_embedded_tweets()
        except Exception as exc:
            results["embedded_tweets_backfill"] = {"error": str(exc)}
            logger.exception("daily_sweep_embedded_tweets_backfill_error", error=str(exc))

        try:
            results["archive"] = _archive_old_games()
        except Exception as exc:
            results["archive"] = {"error": str(exc)}
            logger.exception("daily_sweep_archive_error", error=str(exc))

        # --- Phase 3: Retention — prune old job runs ---
        try:
            results["job_run_pruning"] = _prune_old_job_runs()
        except Exception as exc:
            results["job_run_pruning"] = {"error": str(exc)}
            logger.exception("daily_sweep_job_run_pruning_error", error=str(exc))

        # --- Phase 4: Purge stale fairbet odds for completed games ---
        try:
            results["fairbet_odds_cleanup"] = _purge_completed_game_odds()
        except Exception as exc:
            results["fairbet_odds_cleanup"] = {"error": str(exc)}
            logger.exception("daily_sweep_fairbet_odds_cleanup_error", error=str(exc))

        tracker.summary_data = results
        logger.info("daily_sweep_complete", results=results)
        return results


def _run_social_scrape_2() -> dict:
    """Social Scrape #2: capture postgame reactions for recently-final games.

    Query: games WHERE status='final' AND last_social_at IS NOT NULL
           AND social_scrape_2_at IS NULL AND end_time > now() - 48 hours

    For each game (sequentially, configurable cooldown between games):
    1. Scrape game_date and game_date + 1 (day-bounded)
    2. Map tweets, only keep phase = 'postgame'
    3. Skip tweets already stored (dedup via external_post_id)
    4. Set game.social_scrape_2_at = now()
    """
    import time

    from ..db import db_models
    from ..social.team_collector import TeamTweetCollector
    from ..social.tweet_mapper import map_tweets_for_team
    from ..utils.datetime_utils import ET, now_utc

    now = now_utc()
    lookback = now - timedelta(hours=48)

    with get_session() as session:
        games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.status == db_models.GameStatus.final.value,
                db_models.SportsGame.last_social_at.isnot(None),
                db_models.SportsGame.social_scrape_2_at.is_(None),
                db_models.SportsGame.end_time.isnot(None),
                db_models.SportsGame.end_time > lookback,
            )
            .all()
        )

        if not games:
            logger.debug("sweep_social_scrape_2_no_games")
            return {"games_found": 0, "games_scraped": 0}

        logger.info("sweep_social_scrape_2_start", games_count=len(games))

        try:
            collector = TeamTweetCollector()
        except RuntimeError as exc:
            logger.error("sweep_social_scrape_2_collector_unavailable", error=str(exc))
            return {"games_found": len(games), "games_scraped": 0, "error": str(exc)}

        games_scraped = 0
        total_new = 0
        total_postgame_kept = 0

        for game in games:
            game_date = game.game_date.astimezone(ET).date() if hasattr(game.game_date, "date") else game.game_date
            next_day = game_date + timedelta(days=1)
            team_ids = [game.home_team_id, game.away_team_id]

            game_new = 0
            for team_id in team_ids:
                try:
                    new_tweets = collector.collect_team_tweets(
                        session=session,
                        team_id=team_id,
                        start_date=game_date,
                        end_date=next_day,
                    )
                    game_new += new_tweets
                except Exception as exc:
                    logger.warning(
                        "sweep_social_scrape_2_team_error",
                        game_id=game.id,
                        team_id=team_id,
                        error=str(exc),
                    )

            # Flush pending INSERTs so the mapper's query can see them
            session.flush()

            # Map unmapped tweets
            for team_id in team_ids:
                try:
                    map_tweets_for_team(session, team_id)
                except Exception as exc:
                    logger.warning(
                        "sweep_social_scrape_2_map_error",
                        game_id=game.id,
                        team_id=team_id,
                        error=str(exc),
                    )

            # Count postgame posts for this game (the ones we care about)
            postgame_count = (
                session.query(db_models.TeamSocialPost)
                .filter(
                    db_models.TeamSocialPost.game_id == game.id,
                    db_models.TeamSocialPost.mapping_status == "mapped",
                    db_models.TeamSocialPost.game_phase == "postgame",
                )
                .count()
            )
            total_postgame_kept += postgame_count

            game.social_scrape_2_at = now_utc()
            total_new += game_new
            games_scraped += 1

            logger.info(
                "sweep_social_scrape_2_game_complete",
                game_id=game.id,
                new_tweets=game_new,
                postgame_kept=postgame_count,
            )

            # Inter-game cooldown
            if game != games[-1]:
                time.sleep(settings.social_config.sweep_inter_game_delay_seconds)

        collector.close()
        session.commit()

    logger.info(
        "sweep_social_scrape_2_complete",
        games_scraped=games_scraped,
        total_new=total_new,
        total_postgame_kept=total_postgame_kept,
    )

    return {
        "games_found": len(games),
        "games_scraped": games_scraped,
        "total_new_tweets": total_new,
        "total_postgame_kept": total_postgame_kept,
    }


def _repair_stale_statuses() -> dict:
    """Find scheduled/pregame games past their game_date and check APIs for actual status.

    Games that should have started but are still marked scheduled/pregame
    likely missed a status update. We check the league APIs to get the
    real status.
    """
    from ..db import db_models
    from ..live.nba import NBALiveFeedClient
    from ..live.nhl import NHLLiveFeedClient
    from ..persistence.games import resolve_status_transition
    from ..utils.datetime_utils import now_utc

    now = now_utc()
    # Games with game_date > 3 hours ago that are still scheduled/pregame
    stale_cutoff = now - timedelta(hours=3)
    repaired = 0

    with get_session() as session:
        stale_games = (
            session.query(db_models.SportsGame)
            .filter(
                db_models.SportsGame.status.in_([
                    db_models.GameStatus.scheduled.value,
                    db_models.GameStatus.pregame.value,
                ]),
                db_models.SportsGame.game_date.isnot(None),
                db_models.SportsGame.game_date < stale_cutoff,
            )
            .all()
        )

        if not stale_games:
            logger.debug("sweep_status_repair_none_stale")
            return {"stale_found": 0, "repaired": 0}

        logger.info("sweep_status_repair_found", count=len(stale_games))

        # Group by league for batch API calls
        nba_games = []
        nhl_games = []
        league_cache: dict[int, str] = {}

        for game in stale_games:
            if game.league_id not in league_cache:
                league = session.query(db_models.SportsLeague).get(game.league_id)
                league_cache[game.league_id] = league.code if league else "UNKNOWN"

            code = league_cache[game.league_id]
            if code == "NBA":
                nba_games.append(game)
            elif code == "NHL":
                nhl_games.append(game)
            # NCAAB: skip for now (too many games, handled by batch ingestion)

        # Check NBA scoreboard
        if nba_games:
            try:
                client = NBALiveFeedClient()
                dates = {g.game_date.date() for g in nba_games if g.game_date}
                nba_status_map: dict[str, str] = {}

                for d in dates:
                    scoreboard = client.fetch_scoreboard(d)
                    for sg in scoreboard:
                        nba_status_map[sg.game_id] = sg.status

                for game in nba_games:
                    nba_game_id = (game.external_ids or {}).get("nba_game_id")
                    if nba_game_id and nba_game_id in nba_status_map:
                        api_status = nba_status_map[nba_game_id]
                        new_status = resolve_status_transition(game.status, api_status)
                        if new_status != game.status:
                            logger.info(
                                "sweep_status_repaired",
                                game_id=game.id,
                                league="NBA",
                                from_status=game.status,
                                to_status=new_status,
                            )
                            game.status = new_status
                            game.updated_at = now
                            if new_status == db_models.GameStatus.final.value and game.end_time is None:
                                game.end_time = now
                            repaired += 1
            except Exception as exc:
                logger.warning("sweep_nba_status_check_error", error=str(exc))

        # Check NHL schedule
        if nhl_games:
            try:
                client = NHLLiveFeedClient()
                dates = {g.game_date.date() for g in nhl_games if g.game_date}
                if dates:
                    start = min(dates)
                    end = max(dates)
                    schedule = client.fetch_schedule(start, end)
                    nhl_status_map: dict[int, str] = {}
                    for sg in schedule:
                        nhl_status_map[sg.game_id] = sg.status

                    for game in nhl_games:
                        nhl_game_pk = (game.external_ids or {}).get("nhl_game_pk")
                        if nhl_game_pk:
                            try:
                                pk = int(nhl_game_pk)
                            except (ValueError, TypeError):
                                continue
                            if pk in nhl_status_map:
                                api_status = nhl_status_map[pk]
                                new_status = resolve_status_transition(game.status, api_status)
                                if new_status != game.status:
                                    logger.info(
                                        "sweep_status_repaired",
                                        game_id=game.id,
                                        league="NHL",
                                        from_status=game.status,
                                        to_status=new_status,
                                    )
                                    game.status = new_status
                                    game.updated_at = now
                                    if new_status == db_models.GameStatus.final.value and game.end_time is None:
                                        game.end_time = now
                                    repaired += 1
            except Exception as exc:
                logger.warning("sweep_nhl_status_check_error", error=str(exc))

    return {"stale_found": len(stale_games), "repaired": repaired}


def _backfill_embedded_tweets() -> dict:
    """Call the API to backfill embedded tweets for recent flows.

    Flows generated before social scraping completed may have all-NULL
    embedded_social_post_id. This calls the API endpoint to retroactively
    attach tweets.
    """
    import httpx

    from ..api_client import get_api_headers
    from ..config import settings

    api_base = settings.api_internal_url
    url = f"{api_base}/api/admin/sports/pipeline/backfill-embedded-tweets"

    logger.info("sweep_backfill_embedded_tweets_start")

    with httpx.Client(timeout=30.0, headers=get_api_headers()) as client:
        response = client.post(url, params={"lookback_days": 7})
        response.raise_for_status()
        result = response.json()

    logger.info(
        "sweep_backfill_embedded_tweets_complete",
        total_checked=result.get("total_checked", 0),
        total_backfilled=result.get("total_backfilled", 0),
    )

    return result


def _archive_old_games() -> dict:
    """Archive final games >7 days with complete artifacts.

    This is the same operation as game_state_updater._promote_final_to_archived
    but runs as part of the daily sweep for completeness.
    """
    from ..services.game_state_updater import _promote_final_to_archived

    with get_session() as session:
        archived = _promote_final_to_archived(session)

    return {"archived": archived}


def _prune_old_job_runs(retention_days: int = 7) -> dict:
    """Delete job run records older than retention_days.

    At ~900 rows/day (all recurring tasks), 7-day retention keeps
    the table at ~6300 rows max — trivial for Postgres.
    """
    from ..db import db_models
    from ..utils.datetime_utils import now_utc

    cutoff = now_utc() - timedelta(days=retention_days)

    with get_session() as session:
        deleted = (
            session.query(db_models.SportsJobRun)
            .filter(db_models.SportsJobRun.created_at < cutoff)
            .delete(synchronize_session="fetch")
        )

    logger.info(
        "job_runs_pruned",
        deleted=deleted,
        retention_days=retention_days,
    )

    return {"deleted": deleted, "retention_days": retention_days}


def _purge_completed_game_odds() -> dict:
    """Delete fairbet_game_odds_work rows for final/archived games.

    The work table is meant to hold only active pregame odds. Once a game
    completes, its odds rows are never cleaned up by the per-batch stale
    DELETE (which only fires when new odds are upserted). Without this
    cleanup the table grows unbounded — 1.5M+ rows causing 30+ second
    query times from IO contention.
    """
    from sqlalchemy import text

    with get_session() as session:
        result = session.execute(text("""
            DELETE FROM fairbet_game_odds_work
            WHERE game_id IN (
                SELECT id FROM sports_games
                WHERE status IN ('final', 'archived')
            )
        """))
        deleted = result.rowcount
        session.commit()

    if deleted:
        logger.info("fairbet_odds_purge_complete", deleted=deleted)
    else:
        logger.debug("fairbet_odds_purge_nothing_to_delete")

    return {"deleted": deleted}
