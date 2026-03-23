"""NCAAB boxscore ingestion via College Basketball Data API.

This module handles boxscore data ingestion for NCAAB games using
the College Basketball Data API (api.collegebasketballdata.com).

Benefits:
- Single data source (schedule, PBP, and boxscores)
- Faster ingestion - REST API vs web scraping
- More reliable - official API less likely to break than HTML scraping
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy.orm import Session

from ..logging import logger
from ..models import (
    GameIdentification,
    NormalizedGame,
)
from ..persistence import persist_game_payload
from ..utils.date_utils import season_ending_year
from ..utils.datetime_utils import start_of_et_day_utc
from .ncaab_game_ids import (
    populate_ncaab_game_ids,
    select_games_for_boxscores_ncaab_api,
)


def ingest_boxscores_via_ncaab_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int, int, int]:
    """Ingest NCAAB boxscores using the College Basketball Data API.

    Uses batch fetching to minimize API calls.

    Flow:
    1. Populate cbb_game_id for games missing it (via CBB schedule API)
    2. Select games with cbb_game_id that need boxscore data
    3. Batch fetch all boxscores with 2 API calls (teams + players)
    4. Filter and persist boxscores for requested games

    Args:
        session: Database session
        run_id: Scrape run ID for logging
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have boxscore data
        updated_before: Only include games with stale boxscore data

    Returns:
        Tuple of (games_processed, games_enriched, games_with_stats, errors)
    """
    from ..live.ncaab import NCAABLiveFeedClient

    logger.info(
        "ncaab_boxscore_ingestion_start",
        run_id=run_id,
        start_date=str(start_date),
        end_date=str(end_date),
        only_missing=only_missing,
    )

    # Step 1: Populate missing CBB game IDs
    populate_ncaab_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    session.expire_all()  # ensure select sees freshly-populated external_ids

    # Step 2: Select games for boxscore ingestion
    games = select_games_for_boxscores_ncaab_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "ncaab_boxscore_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0, 0, 0)

    logger.info(
        "ncaab_boxscore_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Batch fetch boxscores
    client = NCAABLiveFeedClient()
    season = season_ending_year(start_date)

    # Filter out cbb_game_id=0 (games with only ncaa_game_id, handled by fallback)
    cbb_game_ids = [cbb_game_id for _, cbb_game_id, _, _, _ in games if cbb_game_id]
    team_names_by_game = {
        cbb_game_id: (home_team_name, away_team_name)
        for _, cbb_game_id, _, home_team_name, away_team_name in games
        if cbb_game_id
    }

    boxscores: dict = {}
    if cbb_game_ids:
        boxscores = client.fetch_boxscores_batch(
            game_ids=cbb_game_ids,
            start_date=start_date,
            end_date=end_date,
            season=season,
            team_names_by_game=team_names_by_game,
        )

    logger.info(
        "ncaab_boxscore_batch_fetched",
        run_id=run_id,
        requested_games=len(games),
        cbb_games=len(cbb_game_ids),
        boxscores_received=len(boxscores),
    )

    # Step 4: Persist boxscores
    games_processed = 0
    games_enriched = 0
    games_with_stats = 0
    errors = 0

    for game_id, cbb_game_id, game_date, _home_team_name, _away_team_name in games:
        boxscore = boxscores.get(cbb_game_id)

        if not boxscore:
            logger.warning(
                "ncaab_boxscore_not_in_batch",
                run_id=run_id,
                game_id=game_id,
                cbb_game_id=cbb_game_id,
            )
            continue

        try:
            boxscore.game_date = start_of_et_day_utc(game_date)

            normalized_game = convert_ncaab_boxscore_to_normalized_game(boxscore)

            result = persist_game_payload(session, normalized_game, game_id=game_id)

            if result.game_id is not None:
                games_processed += 1
                if result.enriched:
                    games_enriched += 1
                if result.has_player_stats:
                    games_with_stats += 1

                session.commit()
                logger.info(
                    "ncaab_boxscore_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                    enriched=result.enriched,
                    player_stats_inserted=result.player_stats.inserted if result.player_stats else 0,
                )

        except Exception as exc:
            session.rollback()
            errors += 1
            logger.warning(
                "ncaab_boxscore_persist_failed",
                run_id=run_id,
                game_id=game_id,
                cbb_game_id=cbb_game_id,
                error=str(exc),
            )
            continue

    # --- NCAA API fallback for games that didn't get boxscores from CBB ---
    ncaa_fallback = _select_ncaa_boxscore_fallback_games(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        already_have_boxscore={
            game_id
            for game_id, cbb_game_id, _, _, _ in games
            if boxscores.get(cbb_game_id)
        },
    )

    if ncaa_fallback:
        logger.info(
            "ncaab_boxscore_ncaa_fallback_start",
            run_id=run_id,
            games=len(ncaa_fallback),
        )

        from ..persistence.boxscores import upsert_player_boxscores, upsert_team_boxscores

        for game_id, ncaa_game_id, home_team_name, away_team_name in ncaa_fallback:
            try:
                boxscore = client.fetch_ncaa_boxscore(
                    ncaa_game_id,
                    home_team_name=home_team_name,
                    away_team_name=away_team_name,
                    game_status="final",
                )

                if not boxscore:
                    continue

                if boxscore.team_boxscores:
                    upsert_team_boxscores(
                        session, game_id, boxscore.team_boxscores,
                        source="ncaa_api",
                    )
                if boxscore.player_boxscores:
                    upsert_player_boxscores(
                        session, game_id, boxscore.player_boxscores,
                        source="ncaa_api",
                    )

                games_processed += 1
                if boxscore.player_boxscores:
                    games_with_stats += 1

                session.commit()
                logger.info(
                    "ncaab_boxscore_ncaa_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    ncaa_game_id=ncaa_game_id,
                    team_stats=len(boxscore.team_boxscores),
                    player_stats=len(boxscore.player_boxscores),
                )

            except Exception as exc:
                session.rollback()
                errors += 1
                logger.warning(
                    "ncaab_boxscore_ncaa_fetch_failed",
                    run_id=run_id,
                    game_id=game_id,
                    ncaa_game_id=ncaa_game_id,
                    error=str(exc),
                )
                continue

    logger.info(
        "ncaab_boxscore_ingestion_complete",
        run_id=run_id,
        games_processed=games_processed,
        games_enriched=games_enriched,
        games_with_stats=games_with_stats,
        errors=errors,
    )

    return (games_processed, games_enriched, games_with_stats, errors)


def _select_ncaa_boxscore_fallback_games(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    already_have_boxscore: set[int],
) -> list[tuple[int, str, str, str]]:
    """Select games with ncaa_game_id that still need boxscores (NCAA API fallback).

    Returns:
        List of (game_id, ncaa_game_id, home_team_name, away_team_name) tuples.
    """
    from sqlalchemy import exists, not_

    from ..db import db_models
    from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NCAAB"
    ).first()
    if not league:
        return []

    ncaa_game_id_expr = db_models.SportsGame.external_ids["ncaa_game_id"].astext

    home_team = db_models.SportsTeam.__table__.alias("home_team")
    away_team = db_models.SportsTeam.__table__.alias("away_team")

    query = session.query(
        db_models.SportsGame.id,
        ncaa_game_id_expr.label("ncaa_game_id"),
        home_team.c.name.label("home_team_name"),
        away_team.c.name.label("away_team_name"),
    ).join(
        home_team,
        db_models.SportsGame.home_team_id == home_team.c.id,
    ).join(
        away_team,
        db_models.SportsGame.away_team_id == away_team.c.id,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        ncaa_game_id_expr.isnot(None),
    )

    if only_missing:
        has_boxscores = exists().where(
            db_models.SportsTeamBoxscore.game_id == db_models.SportsGame.id
        )
        query = query.filter(not_(has_boxscores))

    rows = query.all()
    results = []
    for game_id, ncaa_game_id, home_team_name, away_team_name in rows:
        if not ncaa_game_id:
            continue
        # Skip games already covered by CBB API
        if game_id in already_have_boxscore:
            continue
        if home_team_name and away_team_name:
            results.append((game_id, ncaa_game_id, home_team_name, away_team_name))

    return results


def convert_ncaab_boxscore_to_normalized_game(
    boxscore,  # NCAABBoxscore from live.ncaab
) -> NormalizedGame:
    """Convert NCAABBoxscore to NormalizedGame for persistence."""
    identity = GameIdentification(
        league_code="NCAAB",
        season=boxscore.season,
        season_type="regular",
        game_date=boxscore.game_date,
        home_team=boxscore.home_team,
        away_team=boxscore.away_team,
        source_game_key=str(boxscore.game_id),
    )

    return NormalizedGame(
        identity=identity,
        status="completed" if boxscore.status == "final" else boxscore.status,
        home_score=boxscore.home_score,
        away_score=boxscore.away_score,
        team_boxscores=boxscore.team_boxscores,
        player_boxscores=boxscore.player_boxscores,
    )
