"""Play-by-play scraping phase."""

from __future__ import annotations

from datetime import datetime

from ...logging import logger
from ...utils.datetime_utils import sports_today_et


def ingest_pbp(
    run_id: int,
    config,
    summary: dict,
    start: datetime,
    end: datetime,
    updated_before_dt: datetime | None,
    live_feed_manager,
    supported_live_pbp_leagues: tuple,
    scrapers: dict,
    *,
    get_session,
    start_job_run,
    complete_job_run,
    ingest_pbp_via_nhl_api,
    ingest_pbp_via_ncaab_api,
    ingest_pbp_via_nba_api,
    ingest_pbp_via_mlb_api,
    ingest_pbp_via_sportsref,
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
        if config.league_code not in supported_live_pbp_leagues:
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
                    live_summary = live_feed_manager.ingest_live_data(
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
            from ..pbp_nfl import ingest_pbp_via_nfl_api

            _PBP_DISPATCH: dict[str, tuple] = {
                "NHL": (ingest_pbp_via_nhl_api, "pbp_nhl_api_failed"),
                "NCAAB": (ingest_pbp_via_ncaab_api, "pbp_ncaab_api_failed"),
                "NBA": (ingest_pbp_via_nba_api, "pbp_nba_api_failed"),
                "MLB": (ingest_pbp_via_mlb_api, "pbp_mlb_api_failed"),
                "NFL": (ingest_pbp_via_nfl_api, "pbp_nfl_api_failed"),
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
                            scraper=scrapers.get(config.league_code),
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
