"""Run manager that orchestrates scraper + odds execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..config import settings
from ..config_sports import get_social_enabled_leagues
from ..db import db_models, get_session
from ..live import LiveFeedManager
from ..logging import logger
from ..models import IngestionConfig
from ..persistence import persist_game_payload
from ..scrapers import get_all_scrapers
from ..utils.datetime_utils import now_utc, today_et
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
from .phases.advanced_stats_phase import ingest_advanced_stats
from .phases.boxscore_phase import ingest_boxscores
from .phases.pbp_phase import ingest_pbp
from .phases.social_phase import dispatch_social


def _social_task_exists_for_league(league_code: str) -> bool:
    """Check if a social task is already queued or running for this league.

    Ignores job_runs that have been queued/running for more than 2 hours —
    those are likely orphaned from a worker restart and should not block
    new dispatches.
    """
    try:
        stale_cutoff = datetime.now(UTC) - timedelta(hours=2)
        with get_session() as session:
            existing = (
                session.query(db_models.SportsJobRun)
                .filter(
                    db_models.SportsJobRun.phase == "social",
                    db_models.SportsJobRun.status.in_(["queued", "running"]),
                    db_models.SportsJobRun.leagues.contains([league_code.upper()]),
                    db_models.SportsJobRun.created_at > stale_cutoff,
                )
                .first()
            )
            return existing is not None
    except Exception as exc:
        logger.warning("social_task_exists_check_failed", error=str(exc))
        return True  # Fail-closed: assume task exists to prevent duplicate dispatch


class ScrapeRunManager:
    def __init__(self) -> None:
        self.scrapers = get_all_scrapers()
        self.live_feed_manager = LiveFeedManager()

        # Feature support varies by league. When a toggle is enabled for an unsupported
        # league, we must NOT fail the run; we log and continue.
        self._supported_social_leagues = tuple(get_social_enabled_leagues())
        self._supported_live_pbp_leagues = ("NBA", "NHL", "NCAAB", "MLB", "NFL")

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
    # Private phase methods (delegate to phase modules)
    # ------------------------------------------------------------------

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

    def _ingest_boxscores(self, run_id, config, summary, start, end, updated_before_dt, scraper):
        ingest_boxscores(
            run_id, config, summary, start, end, updated_before_dt, scraper,
            get_session=get_session,
            persist_game_payload=persist_game_payload,
            select_games_for_boxscores=select_games_for_boxscores,
        )

    def _ingest_pbp(self, run_id, config, summary, start, end, updated_before_dt):
        ingest_pbp(
            run_id, config, summary, start, end, updated_before_dt,
            self.live_feed_manager, self._supported_live_pbp_leagues, self.scrapers,
            get_session=get_session,
            start_job_run=start_job_run,
            complete_job_run=complete_job_run,
            ingest_pbp_via_nhl_api=ingest_pbp_via_nhl_api,
            ingest_pbp_via_ncaab_api=ingest_pbp_via_ncaab_api,
            ingest_pbp_via_nba_api=ingest_pbp_via_nba_api,
            ingest_pbp_via_mlb_api=ingest_pbp_via_mlb_api,
            ingest_pbp_via_sportsref=ingest_pbp_via_sportsref,
        )

    def _dispatch_social(self, run_id, config, summary, start, end):
        dispatch_social(
            run_id, config, summary, start, end,
            self._supported_social_leagues,
            get_session=get_session,
            social_task_exists_fn=_social_task_exists_for_league,
            queue_job_run=queue_job_run,
            enforce_social_queue_limit=enforce_social_queue_limit,
        )

    def _ingest_advanced_stats(self, run_id, config, summary, start, end, updated_before_dt):
        ingest_advanced_stats(
            run_id, config, summary, start, end, updated_before_dt,
            get_session=get_session,
            start_job_run=start_job_run,
            complete_job_run=complete_job_run,
        )

    def _run_diagnostics(self, config: IngestionConfig) -> None:
        """Phase: post-run diagnostics.

        Only checks for missing data types that were part of this run.
        """
        with get_session() as session:
            if config.pbp:
                detect_missing_pbp(session, league_code=config.league_code)
            detect_external_id_conflicts(
                session, league_code=config.league_code, source="live_feed"
            )

    def _finalize_run(
        self,
        run_id: int,
        summary: dict,
        phase_errors: list[str] | None = None,
        phases_requested: int = 0,
    ) -> None:
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
        if summary["advanced_stats"] or summary.get("advanced_stats_skipped") or summary.get("advanced_stats_errors"):
            adv_parts = []
            if summary["advanced_stats"]:
                adv_parts.append(f"{summary['advanced_stats']} ingested")
            if summary.get("advanced_stats_skipped"):
                adv_parts.append(f"{summary['advanced_stats_skipped']} skipped")
            if summary.get("advanced_stats_errors"):
                adv_parts.append(f"{summary['advanced_stats_errors']} errors")
            summary_parts.append(f"Advanced Stats: {', '.join(adv_parts)}")

        # Determine final status based on how many phases succeeded vs failed
        phase_errors = phase_errors or []
        if phase_errors:
            summary_parts.append(f"Failed phases: {', '.join(phase_errors)}")
            if len(phase_errors) >= phases_requested and phases_requested > 0:
                # Every requested phase failed — this is an error, not partial success
                status = "error"
            else:
                status = "partial_success"
        else:
            status = "success"

        self._update_run(
            run_id,
            status=status,
            finished_at=now_utc(),
            summary=", ".join(summary_parts) or "No data processed",
        )
        logger.info("scrape_run_complete", run_id=run_id, status=status, summary=summary)

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
            and config.league_code not in ("NHL", "NBA", "NCAAB", "MLB", "NFL")
        ):
            raise RuntimeError(f"No scraper implemented for {config.league_code}")

        self._update_run(run_id, status="running", started_at=now_utc())

        ingest_run_id: int | None = None
        ingest_run_completed = False
        phase_errors: list[str] = []
        try:
            # Odds first: creates games from the Odds API so that
            # boxscore enrichment and PBP have games to work with.
            if config.odds:
                try:
                    self._sync_odds(run_id, config, summary, start, end)
                except Exception as exc:
                    phase_errors.append("odds")
                    logger.error("phase_failed_odds", run_id=run_id, error=str(exc))

            if config.boxscores:
                ingest_run_id = start_job_run("ingest", [config.league_code])

            if config.boxscores:
                try:
                    self._ingest_boxscores(
                        run_id, config, summary, start, end, updated_before_dt, scraper
                    )
                except Exception as exc:
                    phase_errors.append("boxscores")
                    logger.error("phase_failed_boxscores", run_id=run_id, error=str(exc))

            if ingest_run_id is not None:
                complete_job_run(ingest_run_id, "success")
                ingest_run_completed = True

            if config.pbp:
                try:
                    self._ingest_pbp(run_id, config, summary, start, end, updated_before_dt)
                except Exception as exc:
                    phase_errors.append("pbp")
                    logger.error("phase_failed_pbp", run_id=run_id, error=str(exc))

            if config.social:
                try:
                    self._dispatch_social(run_id, config, summary, start, end)
                except Exception as exc:
                    phase_errors.append("social")
                    logger.error("phase_failed_social", run_id=run_id, error=str(exc))

            if config.advanced_stats:
                try:
                    self._ingest_advanced_stats(run_id, config, summary, start, end, updated_before_dt)
                except Exception as exc:
                    phase_errors.append("advanced_stats")
                    logger.error("phase_failed_advanced_stats", run_id=run_id, error=str(exc))

            self._run_diagnostics(config)
            phases_requested = sum([
                config.odds, config.boxscores, config.pbp,
                config.social, config.advanced_stats,
            ])
            self._finalize_run(
                run_id, summary,
                phase_errors=phase_errors,
                phases_requested=phases_requested,
            )

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
