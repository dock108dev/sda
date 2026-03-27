"""Boxscore enrichment phase for existing games."""

from __future__ import annotations

from datetime import UTC, datetime

from ...db import db_models
from ...logging import logger
from ...utils.datetime_utils import end_of_et_day_utc, sports_today_et, start_of_et_day_utc


def ingest_boxscores(
    run_id: int,
    config,
    summary: dict,
    start: datetime,
    end: datetime,
    updated_before_dt: datetime | None,
    scraper: object | None,
    *,
    get_session,
    persist_game_payload,
    select_games_for_boxscores,
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
        # Step 1: Pre-populate game stubs from each league's schedule API
        # so every game exists regardless of Odds API coverage.
        _SCHEDULE_POPULATE = {
            "NHL": ("nhl_boxscore_ingestion", "populate_nhl_games_from_schedule"),
            "NBA": ("nba_boxscore_ingestion", "populate_nba_games_from_schedule"),
            "NCAAB": ("ncaab_boxscore_ingestion", "populate_ncaab_games_from_schedule"),
            "MLB": ("mlb_boxscore_ingestion", "populate_mlb_games_from_schedule"),
            # NFL pre-populates inside its own ingest_boxscores_via_nfl_api
        }

        schedule_entry = _SCHEDULE_POPULATE.get(config.league_code)
        if schedule_entry:
            mod_name, fn_name = schedule_entry
            try:
                import importlib
                mod = importlib.import_module(f"..{mod_name}", package="sports_scraper.services.phases")
                populate_fn = getattr(mod, fn_name)
                with get_session() as session:
                    schedule_created = populate_fn(
                        session,
                        run_id=run_id,
                        start_date=start,
                        end_date=boxscore_end,
                    )
                    session.commit()
                logger.info(
                    "schedule_pre_populate_done",
                    run_id=run_id,
                    league=config.league_code,
                    created=schedule_created,
                )
            except Exception as exc:
                logger.warning(
                    "schedule_pre_populate_failed",
                    run_id=run_id,
                    league=config.league_code,
                    error=str(exc),
                )

        # Step 2: Dispatch to league-specific boxscore ingestion
        _LEAGUE_DISPATCH: dict[str, tuple] = {}

        if config.league_code == "NHL":
            from ..nhl_boxscore_ingestion import ingest_boxscores_via_nhl_api
            _LEAGUE_DISPATCH["NHL"] = (ingest_boxscores_via_nhl_api, "nhl_api", "nhl_boxscore_ingestion_failed")
        elif config.league_code == "NCAAB":
            from ..ncaab_boxscore_ingestion import ingest_boxscores_via_ncaab_api
            _LEAGUE_DISPATCH["NCAAB"] = (ingest_boxscores_via_ncaab_api, "cbb_api", "ncaab_boxscore_ingestion_failed")
        elif config.league_code == "NBA":
            from ..nba_boxscore_ingestion import ingest_boxscores_via_nba_api
            _LEAGUE_DISPATCH["NBA"] = (ingest_boxscores_via_nba_api, "nba_api", "nba_boxscore_ingestion_failed")
        elif config.league_code == "MLB":
            from ..mlb_boxscore_ingestion import ingest_boxscores_via_mlb_api
            _LEAGUE_DISPATCH["MLB"] = (ingest_boxscores_via_mlb_api, "mlb_api", "mlb_boxscore_ingestion_failed")
        elif config.league_code == "NFL":
            from ..nfl_boxscore_ingestion import ingest_boxscores_via_nfl_api
            _LEAGUE_DISPATCH["NFL"] = (ingest_boxscores_via_nfl_api, "espn_nfl_api", "nfl_boxscore_ingestion_failed")

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
                # Each league ingestion function commits per-game internally,
                # so we open a session here but don't add an outer commit —
                # that would hold the connection checked-out for the full run
                # with no benefit (everything is already committed per-game).
                with get_session() as session:
                    games, enriched, with_stats, box_errors = ingest_fn(
                        session,
                        run_id=run_id,
                        start_date=start,
                        end_date=boxscore_end,
                        only_missing=config.only_missing,
                        updated_before=updated_before_dt,
                    )
                summary["games"] = games
                summary["games_enriched"] = enriched
                summary["games_with_stats"] = with_stats
                summary["boxscore_errors"] = box_errors
            except Exception as exc:
                logger.exception(
                    error_label,
                    run_id=run_id,
                    league=config.league_code,
                    error=str(exc),
                )

            # NBA fallback: the CDN API only serves the current season.
            # For historical seasons, use Basketball Reference scraping to
            # pick up any games the API missed.
            if config.league_code == "NBA" and config.boxscores:
                try:
                    from ..nba_historical_ingestion import (
                        ingest_nba_historical_boxscores,
                    )

                    logger.info(
                        "nba_bref_fallback_start",
                        run_id=run_id,
                        start_date=str(start),
                        end_date=str(boxscore_end),
                    )
                    with get_session() as session:
                        bref_games, bref_enriched, bref_stats = (
                            ingest_nba_historical_boxscores(
                                session,
                                run_id=run_id,
                                start_date=start,
                                end_date=boxscore_end,
                                only_missing=True,  # only games the API didn't cover
                            )
                        )
                    if bref_games:
                        summary["games"] += bref_games
                        summary["games_enriched"] += bref_enriched
                        summary["games_with_stats"] += bref_stats
                        logger.info(
                            "nba_bref_fallback_complete",
                            run_id=run_id,
                            games=bref_games,
                            enriched=bref_enriched,
                            with_stats=bref_stats,
                        )
                except Exception as exc:
                    logger.warning(
                        "nba_bref_fallback_failed",
                        run_id=run_id,
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
                        logger.error(
                            "boxscore_scrape_failed", game_id=game_id, error=str(exc)
                        )
                        try:
                            from ..game_selection import record_ingest_error
                            with get_session() as err_session:
                                record_ingest_error(err_session, game_id, str(exc))
                                err_session.commit()
                        except Exception:
                            pass
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
        window_start = start_of_et_day_utc(start)
        window_end = end_of_et_day_utc(bs_end)
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
