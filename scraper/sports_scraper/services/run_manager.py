"""Run manager that orchestrates scraper + odds execution."""

from __future__ import annotations

from datetime import UTC, datetime

from ..celery_app import SOCIAL_BULK_QUEUE
from ..config import settings
from ..config_sports import get_social_enabled_leagues
from ..db import db_models, get_session
from ..live import LiveFeedManager
from ..logging import logger
from ..models import IngestionConfig
from ..persistence import persist_game_payload
from ..scrapers import get_all_scrapers
from ..utils.datetime_utils import now_utc, sports_today_et, today_et
from .diagnostics import detect_external_id_conflicts, detect_missing_pbp
from .game_selection import select_games_for_boxscores
from .job_runs import complete_job_run, enforce_social_queue_limit, queue_job_run, start_job_run
from .pbp_ingestion import (
    ingest_pbp_via_mlb_api,
    ingest_pbp_via_nba_api,
    ingest_pbp_via_ncaab_api,
    ingest_pbp_via_nhl_api,
    ingest_pbp_via_sportsref,
)


class ScrapeRunManager:
    def __init__(self) -> None:
        self.scrapers = get_all_scrapers()
        self.live_feed_manager = LiveFeedManager()

        # Feature support varies by league. When a toggle is enabled for an unsupported
        # league, we must NOT fail the run; we log and continue.
        self._supported_social_leagues = tuple(get_social_enabled_leagues())
        self._supported_live_pbp_leagues = ("NBA", "NHL", "NCAAB", "MLB")

    def _update_run(self, run_id: int, **updates) -> None:
        try:
            with get_session() as session:
                run = (
                    session.query(db_models.SportsScrapeRun)
                    .filter(db_models.SportsScrapeRun.id == run_id)
                    .first()
                )
                if not run:
                    all_runs = (
                        session.query(
                            db_models.SportsScrapeRun.id, db_models.SportsScrapeRun.status
                        )
                        .limit(5)
                        .all()
                    )
                    logger.error(
                        "scrape_run_not_found",
                        run_id=run_id,
                        database_url=settings.database_url[:50] + "...",
                        existing_runs=[r.id for r in all_runs],
                    )
                    return
                for key, value in updates.items():
                    setattr(run, key, value)
                session.flush()
                session.commit()
                logger.info(
                    "scrape_run_updated",
                    run_id=run_id,
                    updates=list(updates.keys()),
                    new_status=updates.get("status"),
                )
        except Exception as exc:
            logger.exception("failed_to_update_run", run_id=run_id, error=str(exc), exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Private phase methods
    # ------------------------------------------------------------------

    def _ingest_boxscores(
        self,
        run_id: int,
        config: IngestionConfig,
        summary: dict,
        start: datetime,
        end: datetime,
        updated_before_dt: datetime | None,
        scraper: object | None,
    ) -> None:
        """Phase: boxscore enrichment for existing games."""
        boxscore_cutoff = sports_today_et()
        boxscore_end = min(end, boxscore_cutoff)
        games_skipped = 0

        if start > boxscore_cutoff:
            logger.info(
                "boxscore_scraping_skipped_future_dates",
                run_id=run_id,
                league=config.league_code,
                start_date=str(start),
                end_date=str(end),
                reason="All dates are today or in the future - no completed games to scrape",
            )
        else:
            # Dispatch table for API-based boxscore ingestion
            _LEAGUE_DISPATCH: dict[str, tuple] = {}

            if config.league_code == "NHL":
                from .nhl_boxscore_ingestion import ingest_boxscores_via_nhl_api

                _LEAGUE_DISPATCH["NHL"] = (
                    ingest_boxscores_via_nhl_api,
                    "nhl_api",
                    "nhl_boxscore_ingestion_failed",
                )
            elif config.league_code == "NCAAB":
                from .ncaab_boxscore_ingestion import ingest_boxscores_via_ncaab_api

                _LEAGUE_DISPATCH["NCAAB"] = (
                    ingest_boxscores_via_ncaab_api,
                    "cbb_api",
                    "ncaab_boxscore_ingestion_failed",
                )
            elif config.league_code == "NBA":
                from .nba_boxscore_ingestion import ingest_boxscores_via_nba_api

                _LEAGUE_DISPATCH["NBA"] = (
                    ingest_boxscores_via_nba_api,
                    "nba_api",
                    "nba_boxscore_ingestion_failed",
                )
            elif config.league_code == "MLB":
                from .mlb_boxscore_ingestion import ingest_boxscores_via_mlb_api

                _LEAGUE_DISPATCH["MLB"] = (
                    ingest_boxscores_via_mlb_api,
                    "mlb_api",
                    "mlb_boxscore_ingestion_failed",
                )

            dispatch = _LEAGUE_DISPATCH.get(config.league_code)

            if dispatch:
                ingest_fn, source_label, error_label = dispatch
                logger.info(
                    "boxscore_scraping_start",
                    run_id=run_id,
                    league=config.league_code,
                    start_date=str(start),
                    end_date=str(boxscore_end),
                    original_end_date=str(end) if end != boxscore_end else None,
                    only_missing=config.only_missing,
                    stage="2_boxscore_enrichment",
                    source=source_label,
                )
                try:
                    with get_session() as session:
                        games, enriched, with_stats = ingest_fn(
                            session,
                            run_id=run_id,
                            start_date=start,
                            end_date=boxscore_end,
                            only_missing=config.only_missing,
                            updated_before=updated_before_dt,
                        )
                        session.commit()
                    summary["games"] = games
                    summary["games_enriched"] = enriched
                    summary["games_with_stats"] = with_stats
                except Exception as exc:
                    logger.exception(
                        error_label,
                        run_id=run_id,
                        league=config.league_code,
                        error=str(exc),
                    )
            elif scraper:
                # Other leagues: Continue using Sports Reference scraper
                logger.info(
                    "boxscore_scraping_start",
                    run_id=run_id,
                    league=config.league_code,
                    start_date=str(start),
                    end_date=str(boxscore_end),
                    original_end_date=str(end) if end != boxscore_end else None,
                    only_missing=config.only_missing,
                    stage="2_boxscore_enrichment",
                    source="sports_reference",
                )

                if config.only_missing or updated_before_dt:
                    # Filter games by criteria
                    with get_session() as session:
                        games_to_scrape = select_games_for_boxscores(
                            session,
                            config.league_code,
                            start,
                            boxscore_end,
                            only_missing=config.only_missing,
                            updated_before=updated_before_dt,
                        )
                    logger.info(
                        "found_games_for_boxscores", count=len(games_to_scrape), run_id=run_id
                    )

                    for game_id, source_key, game_date in games_to_scrape:
                        if not source_key or not game_date:
                            continue
                        try:
                            game_payload = scraper.fetch_single_boxscore(source_key, game_date)
                            if game_payload:
                                with get_session() as session:
                                    result = persist_game_payload(session, game_payload)
                                    session.commit()
                                    if result.game_id is not None:
                                        summary["games"] += 1
                                        if result.enriched:
                                            summary["games_enriched"] += 1
                                        if result.has_player_stats:
                                            summary["games_with_stats"] += 1
                                    else:
                                        games_skipped += 1
                        except Exception as exc:
                            logger.warning(
                                "boxscore_scrape_failed", game_id=game_id, error=str(exc)
                            )
                else:
                    # Scrape all games in date range from Sports Reference
                    for game_payload in scraper.fetch_date_range(start, boxscore_end):
                        try:
                            if not game_payload.identity.source_game_key:
                                logger.warning(
                                    "game_normalization_missing_external_id",
                                    league=config.league_code,
                                    game_date=str(game_payload.identity.game_date),
                                )
                                continue
                            with get_session() as session:
                                result = persist_game_payload(session, game_payload)
                                session.commit()
                                if result.game_id is not None:
                                    summary["games"] += 1
                                    if result.enriched:
                                        summary["games_enriched"] += 1
                                    if result.has_player_stats:
                                        summary["games_with_stats"] += 1
                                else:
                                    # Game not found - this is normal for games not in Odds API
                                    games_skipped += 1
                        except Exception as exc:
                            logger.exception("game_persist_failed", error=str(exc), run_id=run_id)
            else:
                logger.warning(
                    "boxscore_scraping_skipped_no_source",
                    run_id=run_id,
                    league=config.league_code,
                    reason="No scraper available for this league",
                )

        logger.info(
            "boxscores_complete",
            count=summary["games"],
            enriched=summary["games_enriched"],
            with_stats=summary["games_with_stats"],
            skipped=games_skipped,
            run_id=run_id,
        )

        # Gap detection: compare DB games for the date range vs enriched count
        try:
            bs_end = min(end, boxscore_cutoff)
            window_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
            window_end = datetime.combine(bs_end, datetime.max.time(), tzinfo=UTC)
            with get_session() as session:
                total_final_games = (
                    session.query(db_models.SportsGame)
                    .join(
                        db_models.SportsLeague,
                        db_models.SportsGame.league_id == db_models.SportsLeague.id,
                    )
                    .filter(
                        db_models.SportsLeague.code == config.league_code,
                        db_models.SportsGame.status == db_models.GameStatus.final.value,
                        db_models.SportsGame.game_date >= window_start,
                        db_models.SportsGame.game_date <= window_end,
                    )
                    .count()
                )
                if total_final_games > summary["games_enriched"]:
                    gap = total_final_games - summary["games_enriched"]
                    logger.warning(
                        "boxscore_gap_detected",
                        run_id=run_id,
                        league=config.league_code,
                        total_final_games=total_final_games,
                        games_enriched=summary["games_enriched"],
                        gap=gap,
                        start_date=str(start),
                        end_date=str(bs_end),
                    )
        except Exception as exc:
            logger.warning("boxscore_gap_check_failed", run_id=run_id, error=str(exc))

    def _sync_odds(
        self,
        run_id: int,
        config: IngestionConfig,
        summary: dict,
        start: datetime,
        end: datetime,
    ) -> None:
        """Phase: odds synchronization."""
        odds_run_id = start_job_run("odds", [config.league_code])
        logger.info(
            "odds_sync_start",
            run_id=run_id,
            league=config.league_code,
            start_date=str(start),
            end_date=str(end),
        )
        try:
            from ..odds.synchronizer import OddsSynchronizer

            sync = OddsSynchronizer()
            odds_count = sync.sync(config)
            summary["odds"] = odds_count
            logger.info(
                "odds_sync_complete",
                run_id=run_id,
                league=config.league_code,
                odds_count=odds_count,
            )
            complete_job_run(odds_run_id, "success")
        except Exception as exc:
            logger.exception(
                "odds_sync_failed",
                run_id=run_id,
                league=config.league_code,
                error=str(exc),
            )
            complete_job_run(odds_run_id, "error", str(exc))

    def _ingest_pbp(
        self,
        run_id: int,
        config: IngestionConfig,
        summary: dict,
        start: datetime,
        end: datetime,
        updated_before_dt: datetime | None,
    ) -> None:
        """Phase: play-by-play scraping."""
        pbp_run_id = start_job_run("pbp", [config.league_code])
        logger.info(
            "pbp_scraping_start",
            run_id=run_id,
            league=config.league_code,
            start_date=str(start),
            end_date=str(end),
            only_missing=config.only_missing,
            batch_live_feed=config.batch_live_feed,
        )
        if config.batch_live_feed:
            # Live-feed PBP (explicit opt-in only).
            if config.league_code not in self._supported_live_pbp_leagues:
                logger.info(
                    "pbp_not_implemented",
                    run_id=run_id,
                    league=config.league_code,
                    message="Live play-by-play is not implemented for this league; skipping.",
                )
                complete_job_run(pbp_run_id, "success", "pbp_not_implemented")
            else:
                try:
                    with get_session() as session:
                        live_summary = self.live_feed_manager.ingest_live_data(
                            session,
                            config=config,
                            updated_before=updated_before_dt,
                        )
                        session.commit()
                    summary["pbp_games"] += live_summary.pbp_games
                    complete_job_run(pbp_run_id, "success")
                except Exception as exc:
                    logger.exception(
                        "pbp_live_feed_failed",
                        run_id=run_id,
                        league=config.league_code,
                        error=str(exc),
                    )
                    complete_job_run(pbp_run_id, "error", str(exc))
        else:
            # Non-live PBP scraping
            # Only scrape PBP for completed games.
            # sports_today_et() already accounts for the 4 AM boundary.
            pbp_cutoff = sports_today_et()
            pbp_end = min(end, pbp_cutoff)

            if start > pbp_cutoff:
                logger.info(
                    "pbp_skipped_future_dates",
                    run_id=run_id,
                    league=config.league_code,
                    reason="All dates are today or in the future - no completed games for PBP",
                )
                complete_job_run(pbp_run_id, "success", "skipped_future_dates")
            else:
                # Build dispatch dict inside method so patched module-level names are captured
                _PBP_DISPATCH: dict[str, tuple] = {
                    "NHL": (ingest_pbp_via_nhl_api, "pbp_nhl_api_failed"),
                    "NCAAB": (ingest_pbp_via_ncaab_api, "pbp_ncaab_api_failed"),
                    "NBA": (ingest_pbp_via_nba_api, "pbp_nba_api_failed"),
                    "MLB": (ingest_pbp_via_mlb_api, "pbp_mlb_api_failed"),
                }

                dispatch = _PBP_DISPATCH.get(config.league_code)

                if dispatch:
                    pbp_fn, error_label = dispatch
                    try:
                        with get_session() as session:
                            pbp_games, pbp_events = pbp_fn(
                                session,
                                run_id=run_id,
                                start_date=start,
                                end_date=pbp_end,
                                only_missing=config.only_missing,
                                updated_before=updated_before_dt,
                            )
                            session.commit()
                        summary["pbp_games"] += pbp_games
                        complete_job_run(pbp_run_id, "success")
                    except Exception as exc:
                        logger.exception(
                            error_label,
                            run_id=run_id,
                            league=config.league_code,
                            error=str(exc),
                        )
                        complete_job_run(pbp_run_id, "error", str(exc))
                else:
                    # Other leagues: Use Sports Reference for PBP
                    try:
                        with get_session() as session:
                            pbp_games, pbp_events = ingest_pbp_via_sportsref(
                                session,
                                run_id=run_id,
                                league_code=config.league_code,
                                scraper=self.scrapers.get(config.league_code),
                                start_date=start,
                                end_date=pbp_end,
                                only_missing=config.only_missing,
                                updated_before=updated_before_dt,
                            )
                            session.commit()
                        summary["pbp_games"] += pbp_games
                        complete_job_run(pbp_run_id, "success")
                    except Exception as exc:
                        logger.exception(
                            "pbp_sportsref_failed",
                            run_id=run_id,
                            league=config.league_code,
                            error=str(exc),
                        )
                        complete_job_run(pbp_run_id, "error", str(exc))

        logger.info("pbp_complete", count=summary["pbp_games"], run_id=run_id)

    def _dispatch_social(
        self,
        run_id: int,
        config: IngestionConfig,
        summary: dict,
        start: datetime,
        end: datetime,
    ) -> None:
        """Phase: dispatch social scraping to dedicated worker.

        Creates a 'queued' DB record *before* dispatching so the task is
        immediately visible (and cancellable) in the RunsDrawer.  Oldest
        queued social tasks are evicted when the queue exceeds 10.
        """
        import uuid
        from datetime import timedelta

        if config.league_code not in self._supported_social_leagues:
            logger.info(
                "x_social_not_implemented",
                run_id=run_id,
                league=config.league_code,
                message="X/social scraping is not yet implemented for this league; skipping.",
            )
        else:
            from ..jobs.social_tasks import collect_team_social, handle_social_task_failure

            # Enforce FIFO queue cap before adding a new task
            enforce_social_queue_limit(10)

            # Cap social date range to yesterday+today to reduce team count.
            # For historical backfills where end < yesterday, use the original range as-is.
            yesterday = today_et() - timedelta(days=1)
            social_start = max(start, yesterday) if end >= yesterday else start

            if social_start > end:
                logger.info(
                    "social_dispatch_skipped_empty_range",
                    run_id=run_id,
                    league=config.league_code,
                    social_start=str(social_start),
                    end=str(end),
                    reason="Capped social_start exceeds end date",
                )
                return

            # Pre-generate Celery task ID so we can store it in the DB
            task_id = str(uuid.uuid4())
            job_run_id = queue_job_run("social", [config.league_code], celery_task_id=task_id)

            logger.info(
                "social_dispatched_to_worker",
                run_id=run_id,
                league=config.league_code,
                start_date=str(social_start),
                end_date=str(end),
                job_run_id=job_run_id,
                celery_task_id=task_id,
            )
            collect_team_social.apply_async(
                args=[config.league_code, str(social_start), str(end)],
                kwargs={"scrape_run_id": run_id, "job_run_id": job_run_id},
                queue=SOCIAL_BULK_QUEUE,
                task_id=task_id,
                link_error=handle_social_task_failure.s(run_id),
            )
            summary["social_posts"] = "dispatched"

    def _ingest_advanced_stats(
        self,
        run_id: int,
        config: IngestionConfig,
        summary: dict,
        start: datetime,
        end: datetime,
        updated_before_dt: datetime | None,
    ) -> None:
        """Phase: MLB Statcast advanced stats ingestion."""
        if config.league_code != "MLB":
            logger.info(
                "advanced_stats_skip_non_mlb",
                run_id=run_id,
                league=config.league_code,
                message="Advanced stats only available for MLB; skipping.",
            )
            return

        adv_run_id = start_job_run("advanced_stats", ["MLB"])
        logger.info(
            "advanced_stats_start",
            run_id=run_id,
            league=config.league_code,
            start_date=str(start),
            end_date=str(end),
            only_missing=config.only_missing,
        )
        try:
            from .mlb_advanced_stats_ingestion import ingest_advanced_stats_for_game

            with get_session() as session:
                window_start = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
                window_end = datetime.combine(end, datetime.max.time(), tzinfo=UTC)

                query = (
                    session.query(db_models.SportsGame)
                    .join(
                        db_models.SportsLeague,
                        db_models.SportsGame.league_id == db_models.SportsLeague.id,
                    )
                    .filter(
                        db_models.SportsLeague.code == "MLB",
                        db_models.SportsGame.status == db_models.GameStatus.final.value,
                        db_models.SportsGame.game_date >= window_start,
                        db_models.SportsGame.game_date <= window_end,
                    )
                )

                if config.only_missing:
                    query = query.filter(db_models.SportsGame.last_advanced_stats_at.is_(None))

                if updated_before_dt:
                    query = query.filter(
                        (db_models.SportsGame.last_advanced_stats_at.is_(None))
                        | (db_models.SportsGame.last_advanced_stats_at < updated_before_dt)
                    )

                games = query.all()
                count = 0
                for game in games:
                    try:
                        ingest_advanced_stats_for_game(session, game.id)
                        count += 1
                    except Exception as exc:
                        logger.warning(
                            "advanced_stats_game_failed",
                            game_id=game.id,
                            error=str(exc),
                        )

                session.commit()

            summary["advanced_stats"] = count
            logger.info(
                "advanced_stats_complete",
                run_id=run_id,
                count=count,
                total_games=len(games),
            )
            complete_job_run(adv_run_id, "success")
        except Exception as exc:
            logger.exception(
                "advanced_stats_failed",
                run_id=run_id,
                league=config.league_code,
                error=str(exc),
            )
            complete_job_run(adv_run_id, "error", str(exc))

    def _run_diagnostics(self, config: IngestionConfig) -> None:
        """Phase: post-run diagnostics."""
        with get_session() as session:
            detect_missing_pbp(session, league_code=config.league_code)
            detect_external_id_conflicts(
                session, league_code=config.league_code, source="live_feed"
            )

    def _finalize_run(self, run_id: int, summary: dict) -> None:
        """Phase: build summary string and mark run complete."""
        summary_parts = []
        if summary["games"]:
            summary_parts.append(
                f"Games: {summary['games']} ({summary['games_enriched']} enriched, {summary['games_with_stats']} with stats)"
            )
        if summary["odds"]:
            summary_parts.append(f"Odds: {summary['odds']}")
        if summary["social_posts"]:
            social_val = summary["social_posts"]
            if social_val == "dispatched":
                summary_parts.append("Social: dispatched to worker")
            else:
                summary_parts.append(f"Social: {social_val}")
        if summary["pbp_games"]:
            summary_parts.append(f"PBP: {summary['pbp_games']}")
        if summary["advanced_stats"]:
            summary_parts.append(f"Advanced Stats: {summary['advanced_stats']}")

        self._update_run(
            run_id,
            status="success",
            finished_at=now_utc(),
            summary=", ".join(summary_parts) or "No data processed",
        )
        logger.info("scrape_run_complete", run_id=run_id, summary=summary)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(self, run_id: int, config: IngestionConfig) -> dict:
        summary: dict[str, int | str] = {
            "games": 0,
            "games_enriched": 0,  # Games enriched with boxscore data
            "games_with_stats": 0,  # Games that had player stats upserted
            "odds": 0,
            "social_posts": 0,
            "pbp_games": 0,
            "advanced_stats": 0,
        }
        start = config.start_date or today_et()
        end = config.end_date or start
        scraper = self.scrapers.get(config.league_code)

        # Convert updated_before date to datetime if provided
        updated_before_dt = (
            datetime.combine(config.updated_before, datetime.min.time()).replace(tzinfo=UTC)
            if config.updated_before
            else None
        )

        logger.info(
            "scrape_run_config",
            run_id=run_id,
            league=config.league_code,
            boxscores=config.boxscores,
            odds=config.odds,
            social=config.social,
            pbp=config.pbp,
            advanced_stats=config.advanced_stats,
            only_missing=config.only_missing,
            updated_before=str(config.updated_before) if config.updated_before else None,
            start_date=str(start),
            end_date=str(end),
        )

        # NHL, NBA, NCAAB, and MLB use official APIs for boxscores, so scraper is not required
        if (
            not scraper
            and config.boxscores
            and config.league_code not in ("NHL", "NBA", "NCAAB", "MLB")
        ):
            raise RuntimeError(f"No scraper implemented for {config.league_code}")

        self._update_run(run_id, status="running", started_at=now_utc())

        ingest_run_id: int | None = None
        ingest_run_completed = False
        try:
            # Odds first: creates games from the Odds API so that
            # boxscore enrichment and PBP have games to work with.
            if config.odds:
                self._sync_odds(run_id, config, summary, start, end)

            if config.boxscores:
                ingest_run_id = start_job_run("ingest", [config.league_code])

            if config.boxscores:
                self._ingest_boxscores(
                    run_id, config, summary, start, end, updated_before_dt, scraper
                )

            if ingest_run_id is not None:
                complete_job_run(ingest_run_id, "success")
                ingest_run_completed = True

            if config.pbp:
                self._ingest_pbp(run_id, config, summary, start, end, updated_before_dt)

            if config.social:
                self._dispatch_social(run_id, config, summary, start, end)

            if config.advanced_stats:
                self._ingest_advanced_stats(run_id, config, summary, start, end, updated_before_dt)

            self._run_diagnostics(config)
            self._finalize_run(run_id, summary)

        except Exception as exc:
            if ingest_run_id is not None and not ingest_run_completed:
                complete_job_run(ingest_run_id, "error", str(exc))
            logger.exception("scrape_run_failed", run_id=run_id, error=str(exc))
            self._update_run(
                run_id,
                status="error",
                finished_at=now_utc(),
                error_details=str(exc),
            )
            raise

        return summary
