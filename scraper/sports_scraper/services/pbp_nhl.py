"""NHL play-by-play ingestion via official NHL API (api-web.nhle.com)."""

from __future__ import annotations

from datetime import date, datetime

from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc, to_et_date

from sqlalchemy import exists, not_, or_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger


def select_games_for_pbp_nhl_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int]]:
    """Return game ids and NHL game IDs for NHL API play-by-play ingestion.

    NHL PBP must be fetched via the official NHL API using the NHL game ID
    (like 2025020767) stored in external_ids['nhl_game_pk'].
    Sports Reference does not provide NHL PBP.

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have PBP data
        updated_before: Only include games with stale PBP data

    Returns:
        List of (game_id, nhl_game_id) tuples for games needing PBP
    """
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NHL"
    ).first()
    if not league:
        return []

    # NHL game ID is stored in external_ids JSONB field under 'nhl_game_pk' key
    nhl_game_pk_expr = db_models.SportsGame.external_ids["nhl_game_pk"].astext

    query = session.query(
        db_models.SportsGame.id,
        nhl_game_pk_expr.label("nhl_game_pk"),
        db_models.SportsGame.status,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        # nhl_game_pk is required for NHL API PBP fetch
        nhl_game_pk_expr.isnot(None),
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
    for game_id, nhl_game_pk, status in rows:
        if nhl_game_pk:
            try:
                nhl_game_id = int(nhl_game_pk)
                results.append((game_id, nhl_game_id))
            except (ValueError, TypeError):
                logger.warning(
                    "nhl_pbp_invalid_game_pk",
                    game_id=game_id,
                    nhl_game_pk=nhl_game_pk,
                )
    return results


def populate_nhl_game_ids(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Populate nhl_game_pk for NHL games that don't have it.

    Fetches the NHL schedule and matches games by team + date to populate
    the external_ids['nhl_game_pk'] field needed for PBP fetching.

    Returns:
        Number of games updated with NHL game IDs
    """
    from ..live.nhl import NHLLiveFeedClient

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NHL"
    ).first()
    if not league:
        return 0

    # Find games without nhl_game_pk
    nhl_game_pk_expr = db_models.SportsGame.external_ids["nhl_game_pk"].astext

    games_missing_pk = (
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
                nhl_game_pk_expr.is_(None),
                nhl_game_pk_expr == "",
            ),
        )
        .all()
    )

    if not games_missing_pk:
        logger.info(
            "nhl_game_ids_all_present",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        return 0

    logger.info(
        "nhl_game_ids_missing",
        run_id=run_id,
        count=len(games_missing_pk),
        start_date=str(start_date),
        end_date=str(end_date),
    )

    # Build team ID to abbreviation mapping
    teams = session.query(db_models.SportsTeam).filter(
        db_models.SportsTeam.league_id == league.id
    ).all()
    team_id_to_abbr = {t.id: t.abbreviation for t in teams}

    # Fetch NHL schedule
    client = NHLLiveFeedClient()
    nhl_games = client.fetch_schedule(start_date, end_date)

    # Build lookup: (home_abbr, away_abbr, date) -> nhl_game_id
    nhl_lookup: dict[tuple[str, str, date], int] = {}
    for ng in nhl_games:
        key = (
            ng.home_team.abbreviation.upper(),
            ng.away_team.abbreviation.upper(),
            to_et_date(ng.game_date),
        )
        nhl_lookup[key] = ng.game_id

    # Log both sides of the lookup for debugging mismatches
    if nhl_lookup:
        sample_api_keys = list(nhl_lookup.keys())[:3]
        logger.info(
            "nhl_game_id_lookup_built",
            run_id=run_id,
            api_keys_count=len(nhl_lookup),
            sample_api_keys=[f"{k[0]}v{k[1]}@{k[2]}" for k in sample_api_keys],
        )

    # Match and update
    updated = 0
    for game_id, game_date, home_team_id, away_team_id in games_missing_pk:
        home_abbr = team_id_to_abbr.get(home_team_id, "").upper()
        away_abbr = team_id_to_abbr.get(away_team_id, "").upper()
        game_day = to_et_date(game_date) if game_date else None

        if not home_abbr or not away_abbr or not game_day:
            logger.debug(
                "nhl_game_id_skip_no_abbr",
                game_id=game_id,
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_abbr=home_abbr,
                away_abbr=away_abbr,
            )
            continue

        key = (home_abbr, away_abbr, game_day)
        nhl_game_id = nhl_lookup.get(key)

        if not nhl_game_id:
            logger.debug(
                "nhl_game_id_no_match",
                game_id=game_id,
                db_key=f"{home_abbr}v{away_abbr}@{game_day}",
            )

        if nhl_game_id:
            game = session.query(db_models.SportsGame).get(game_id)
            if game:
                # Update external_ids with nhl_game_pk
                new_external_ids = dict(game.external_ids) if game.external_ids else {}
                new_external_ids["nhl_game_pk"] = nhl_game_id
                game.external_ids = new_external_ids
                updated += 1
                logger.info(
                    "nhl_game_id_populated",
                    run_id=run_id,
                    game_id=game_id,
                    nhl_game_pk=nhl_game_id,
                    home=home_abbr,
                    away=away_abbr,
                )

    session.flush()
    logger.info(
        "nhl_game_ids_populated",
        run_id=run_id,
        updated=updated,
        total_missing=len(games_missing_pk),
    )
    return updated


def ingest_pbp_via_nhl_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int]:
    """Ingest PBP using the official NHL API (api-web.nhle.com).

    This is the only way to get NHL play-by-play data - Sports Reference
    does not provide it.

    Flow:
    1. Populate nhl_game_pk for games missing it (via NHL schedule API)
    2. Select games with nhl_game_pk that need PBP
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
    # Step 1: Populate missing NHL game IDs
    populate_nhl_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )

    # Step 2: Select games for PBP ingestion
    games = select_games_for_pbp_nhl_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "nhl_pbp_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0)

    logger.info(
        "nhl_pbp_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Fetch and persist PBP via SSOT game_processors
    from .game_processors import process_game_pbp_nhl

    pbp_games = 0
    pbp_events = 0

    for game_id, nhl_game_id in games:
        try:
            game = session.query(db_models.SportsGame).get(game_id)
            if not game:
                continue

            result = process_game_pbp_nhl(session, game)

            if result.events_inserted:
                pbp_games += 1
                pbp_events += result.events_inserted

                logger.info(
                    "nhl_pbp_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    nhl_game_id=nhl_game_id,
                    events_inserted=result.events_inserted,
                )
            elif not result.events_inserted and result.api_calls > 0:
                logger.warning(
                    "nhl_pbp_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    nhl_game_id=nhl_game_id,
                )

            session.commit()

        except Exception as exc:
            session.rollback()
            logger.warning(
                "nhl_pbp_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                nhl_game_id=nhl_game_id,
                error=str(exc),
            )
            continue

    logger.info(
        "nhl_pbp_ingestion_complete",
        run_id=run_id,
        games_processed=pbp_games,
        total_events=pbp_events,
    )

    return (pbp_games, pbp_events)
