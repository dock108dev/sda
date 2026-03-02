"""NHL boxscore ingestion via official NHL API.

This module handles boxscore data ingestion for NHL games using
the official NHL API (api-web.nhle.com).

Benefits:
- Single data source (schedule, PBP, and boxscores)
- Faster ingestion - REST API vs web scraping
- More reliable - official API less likely to break than HTML scraping
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..utils.datetime_utils import end_of_et_day_utc

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import (
    GameIdentification,
    NormalizedGame,
)
from ..persistence import persist_game_payload
from ..utils.date_utils import season_ending_year
from ..utils.datetime_utils import date_to_utc_datetime
from .pbp_ingestion import populate_nhl_game_ids


def select_games_for_boxscores_nhl_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int, date]]:
    """Return game ids and NHL game IDs for NHL API boxscore ingestion.

    NHL boxscores are fetched via the official NHL API using the NHL game ID
    (like 2025020767) stored in external_ids['nhl_game_pk'].

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have boxscore data
        updated_before: Only include games with stale boxscore data

    Returns:
        List of (game_id, nhl_game_id, game_date) tuples for games needing boxscores
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
        db_models.SportsGame.game_date,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
    )

    if only_missing:
        has_boxscores = exists().where(
            db_models.SportsTeamBoxscore.game_id == db_models.SportsGame.id
        )
        query = query.filter(not_(has_boxscores))

    if updated_before:
        has_fresh = exists().where(
            db_models.SportsTeamBoxscore.game_id == db_models.SportsGame.id,
            db_models.SportsTeamBoxscore.updated_at >= updated_before,
        )
        query = query.filter(not_(has_fresh))

    rows = query.all()
    results = []
    for game_id, nhl_game_pk, game_date in rows:
        if nhl_game_pk:
            try:
                nhl_game_id = int(nhl_game_pk)
                game_day = game_date.date() if game_date else None
                if game_day:
                    results.append((game_id, nhl_game_id, game_day))
            except (ValueError, TypeError):
                logger.warning(
                    "nhl_boxscore_invalid_game_pk",
                    game_id=game_id,
                    nhl_game_pk=nhl_game_pk,
                )
    return results


def ingest_boxscores_via_nhl_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int, int]:
    """Ingest NHL boxscores using the official NHL API.

    Flow:
    1. Populate nhl_game_pk for games missing it (via NHL schedule API)
    2. Select games with nhl_game_pk that need boxscore data
    3. Fetch boxscore from NHL API for each game
    4. Convert to NormalizedGame with team/player boxscores
    5. Persist via existing persist_game_payload()

    Args:
        session: Database session
        run_id: Scrape run ID for logging
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have boxscore data
        updated_before: Only include games with stale boxscore data

    Returns:
        Tuple of (games_processed, games_enriched, games_with_stats)
    """
    from ..live.nhl import NHLLiveFeedClient

    # Step 1: Populate missing NHL game IDs
    populate_nhl_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    session.expire_all()  # ensure select sees freshly-populated external_ids

    # Step 2: Select games for boxscore ingestion
    games = select_games_for_boxscores_nhl_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "nhl_boxscore_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0, 0)

    logger.info(
        "nhl_boxscore_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Fetch and persist boxscores
    client = NHLLiveFeedClient()
    games_processed = 0
    games_enriched = 0
    games_with_stats = 0

    for game_id, nhl_game_id, game_date in games:
        try:
            boxscore = client.fetch_boxscore(nhl_game_id)

            if not boxscore:
                logger.warning(
                    "nhl_boxscore_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    nhl_game_id=nhl_game_id,
                )
                continue

            normalized_game = convert_nhl_boxscore_to_normalized_game(
                boxscore, game_date
            )

            result = persist_game_payload(session, normalized_game)

            if result.game_id is not None:
                games_processed += 1
                if result.enriched:
                    games_enriched += 1
                if result.has_player_stats:
                    games_with_stats += 1

                logger.info(
                    "nhl_boxscore_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    nhl_game_id=nhl_game_id,
                    enriched=result.enriched,
                    player_stats_inserted=result.player_stats.inserted if result.player_stats else 0,
                )

        except Exception as exc:
            logger.warning(
                "nhl_boxscore_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                nhl_game_id=nhl_game_id,
                error=str(exc),
            )
            continue

    logger.info(
        "nhl_boxscore_ingestion_complete",
        run_id=run_id,
        games_processed=games_processed,
        games_enriched=games_enriched,
        games_with_stats=games_with_stats,
    )

    return (games_processed, games_enriched, games_with_stats)


def convert_nhl_boxscore_to_normalized_game(
    boxscore,  # NHLBoxscore from live.nhl
    game_date: date,
) -> NormalizedGame:
    """Convert NHLBoxscore to NormalizedGame for persistence.

    This bridges the NHL API boxscore format to our normalized persistence layer.
    """
    identity = GameIdentification(
        league_code="NHL",
        season=season_ending_year(game_date),
        season_type="regular",
        game_date=date_to_utc_datetime(game_date),
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
