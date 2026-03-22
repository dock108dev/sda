"""NBA play-by-play ingestion via official NBA API (cdn.nba.com)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc, to_et_date

from sqlalchemy import exists, not_, or_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger


def select_games_for_pbp_nba_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, str]]:
    """Return game ids and NBA game IDs for NBA API play-by-play ingestion.

    NBA PBP is fetched via the official NBA API using the NBA game ID
    stored in external_ids['nba_game_id'].

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        List of (game_id, nba_game_id) tuples for games needing PBP
    """
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NBA"
    ).first()
    if not league:
        return []

    # NBA game ID is stored in external_ids JSONB field under 'nba_game_id' key
    nba_game_id_expr = db_models.SportsGame.external_ids["nba_game_id"].astext

    query = session.query(
        db_models.SportsGame.id,
        nba_game_id_expr.label("nba_game_id"),
        db_models.SportsGame.status,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        # nba_game_id is required for NBA API PBP fetch
        nba_game_id_expr.isnot(None),
    )

    if only_missing:
        has_pbp = exists().where(db_models.SportsGamePlay.game_id == db_models.SportsGame.id)
        query = query.filter(not_(has_pbp))

    if updated_before:
        has_fresh = exists().where(
            db_models.SportsGamePlay.game_id == db_models.SportsGame.id,
            db_models.SportsGamePlay.updated_at >= updated_before,
        )
        query = query.filter(not_(has_fresh))

    rows = query.all()
    results = []
    for game_id, nba_game_id, status in rows:
        if nba_game_id:
            # NBA game IDs are strings like "0022400123"
            results.append((game_id, nba_game_id))
    return results


def populate_nba_game_ids(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Populate nba_game_id for NBA games that don't have it.

    Fetches the NBA scoreboard and matches games by team abbreviations + date
    to populate the external_ids['nba_game_id'] field needed for PBP fetching.

    Returns:
        Number of games updated with NBA game IDs
    """
    from ..live.nba import NBALiveFeedClient

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NBA"
    ).first()
    if not league:
        return 0

    # Find games without nba_game_id
    nba_game_id_expr = db_models.SportsGame.external_ids["nba_game_id"].astext

    games_missing_id = (
        session.query(
            db_models.SportsGame.id,
            db_models.SportsGame.game_date,
            db_models.SportsGame.home_team_id,
            db_models.SportsGame.away_team_id,
        )
        .filter(
            db_models.SportsGame.league_id == league.id,
            db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
            db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
            or_(
                nba_game_id_expr.is_(None),
                nba_game_id_expr == "",
            ),
        )
        .all()
    )

    if not games_missing_id:
        logger.info(
            "nba_game_ids_all_present",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        return 0

    logger.info(
        "nba_game_ids_missing",
        run_id=run_id,
        count=len(games_missing_id),
        start_date=str(start_date),
        end_date=str(end_date),
    )

    # Build team ID to abbreviation mapping
    teams = session.query(db_models.SportsTeam).filter(
        db_models.SportsTeam.league_id == league.id
    ).all()
    team_id_to_abbr = {t.id: t.abbreviation for t in teams}

    # Fetch NBA scoreboard for each day in range
    client = NBALiveFeedClient()
    nba_lookup: dict[tuple[str, str, date], str] = {}

    current_date = start_date
    while current_date <= end_date:
        try:
            nba_games = client.fetch_scoreboard(current_date)
            for ng in nba_games:
                key = (
                    ng.home_abbr.upper(),
                    ng.away_abbr.upper(),
                    current_date,
                )
                nba_lookup[key] = ng.game_id
        except Exception as exc:
            logger.warning(
                "nba_scoreboard_fetch_failed",
                run_id=run_id,
                date=str(current_date),
                error=str(exc),
            )
        current_date += timedelta(days=1)

    # Match and update
    updated = 0
    for game_id, game_date, home_team_id, away_team_id in games_missing_id:
        home_abbr = team_id_to_abbr.get(home_team_id, "").upper()
        away_abbr = team_id_to_abbr.get(away_team_id, "").upper()
        game_day = to_et_date(game_date) if game_date else None

        if not home_abbr or not away_abbr or not game_day:
            continue

        key = (home_abbr, away_abbr, game_day)
        nba_game_id = nba_lookup.get(key)

        if nba_game_id:
            game = session.query(db_models.SportsGame).get(game_id)
            if game:
                # Update external_ids with nba_game_id
                new_external_ids = dict(game.external_ids) if game.external_ids else {}
                new_external_ids["nba_game_id"] = nba_game_id
                game.external_ids = new_external_ids
                updated += 1
                logger.info(
                    "nba_game_id_populated",
                    run_id=run_id,
                    game_id=game_id,
                    nba_game_id=nba_game_id,
                    home=home_abbr,
                    away=away_abbr,
                )

    session.flush()
    logger.info(
        "nba_game_ids_populated",
        run_id=run_id,
        updated=updated,
        total_missing=len(games_missing_id),
    )
    return updated


def ingest_pbp_via_nba_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int]:
    """Ingest PBP using the official NBA API (cdn.nba.com).

    Flow:
    1. Populate nba_game_id for games missing it (via NBA scoreboard API)
    2. Select games with nba_game_id that need PBP
    3. Fetch and persist PBP for each game

    Args:
        session: Database session
        run_id: Scrape run ID for logging
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        Tuple of (games_with_pbp, total_events_inserted)
    """
    logger.info(
        "nba_pbp_ingestion_start",
        run_id=run_id,
        start_date=str(start_date),
        end_date=str(end_date),
        only_missing=only_missing,
    )

    # Step 1: Populate missing NBA game IDs
    populate_nba_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )

    # Step 2: Select games for PBP ingestion
    games = select_games_for_pbp_nba_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "nba_pbp_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0)

    logger.info(
        "nba_pbp_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Fetch and persist PBP via SSOT game_processors
    from .game_processors import process_game_pbp_nba

    pbp_games = 0
    pbp_events = 0

    for game_id, nba_game_id in games:
        try:
            game = session.query(db_models.SportsGame).get(game_id)
            if not game:
                continue

            result = process_game_pbp_nba(session, game)

            if result.events_inserted:
                pbp_games += 1
                pbp_events += result.events_inserted

                logger.info(
                    "nba_pbp_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    nba_game_id=nba_game_id,
                    events_inserted=result.events_inserted,
                )
            elif not result.events_inserted and result.api_calls > 0:
                logger.warning(
                    "nba_pbp_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    nba_game_id=nba_game_id,
                )

            session.commit()

        except Exception as exc:
            session.rollback()
            logger.warning(
                "nba_pbp_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                nba_game_id=nba_game_id,
                error=str(exc),
            )
            continue

    logger.info(
        "nba_pbp_ingestion_complete",
        run_id=run_id,
        games_processed=pbp_games,
        total_events=pbp_events,
    )

    return (pbp_games, pbp_events)
