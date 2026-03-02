"""NBA boxscore ingestion via official NBA CDN API.

This module handles boxscore data ingestion for NBA games using
the NBA CDN API (cdn.nba.com).

Benefits:
- Data available immediately after games end (unlike Basketball Reference)
- Single data source (scoreboard, PBP, and boxscores from same API)
- More reliable — official API less likely to break than HTML scraping

Matching strategy: Uses direct game_id from the DB (populated via
nba_game_id in external_ids). No team+date re-lookup needed — we
already know which game we're enriching.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..utils.datetime_utils import end_of_et_day_utc

from sqlalchemy import exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import TeamIdentity
from ..persistence.boxscores import (
    PlayerBoxscoreStats,
    upsert_player_boxscores,
    upsert_team_boxscores,
)
from ..persistence.games import _normalize_status, resolve_status_transition
from ..utils.datetime_utils import now_utc
from .pbp_nba import populate_nba_game_ids


def select_games_for_boxscores_nba_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, str, date]]:
    """Return game ids and NBA game IDs for NBA API boxscore ingestion.

    NBA boxscores are fetched via the NBA CDN API using the NBA game ID
    (like "0022400123") stored in external_ids['nba_game_id'].

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have boxscore data
        updated_before: Only include games with stale boxscore data

    Returns:
        List of (game_id, nba_game_id, game_date) tuples for games needing boxscores
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
    for game_id, nba_game_id, game_date in rows:
        if nba_game_id:
            game_day = game_date.date() if game_date else None
            if game_day:
                results.append((game_id, nba_game_id, game_day))
    return results


def _team_identity_from_db(session: Session, team_id: int) -> TeamIdentity:
    """Build a TeamIdentity from an existing DB team record."""
    team = session.get(db_models.SportsTeam, team_id)
    league = session.get(db_models.SportsLeague, team.league_id) if team else None
    return TeamIdentity(
        league_code=league.code if league else "NBA",
        name=team.name if team else "Unknown",
        abbreviation=team.abbreviation if team else "UNK",
    )


def _enrich_game_from_boxscore(
    session: Session,
    game: db_models.SportsGame,
    boxscore,
) -> bool:
    """Update game with scores, status, and source_game_key from boxscore.

    Returns True if game was updated.
    """
    updated = False

    if boxscore.home_score is not None and boxscore.home_score != game.home_score:
        game.home_score = boxscore.home_score
        updated = True
    if boxscore.away_score is not None and boxscore.away_score != game.away_score:
        game.away_score = boxscore.away_score
        updated = True

    # Set source_game_key to the NBA game ID if not already set
    if boxscore.game_id and not game.source_game_key:
        game.source_game_key = str(boxscore.game_id)
        updated = True

    # Transition status (e.g., scheduled → final)
    normalized_status = _normalize_status(
        "completed" if boxscore.status == "final" else boxscore.status
    )
    new_status = resolve_status_transition(game.status, normalized_status)
    if new_status != game.status:
        game.status = new_status
        updated = True

    if updated:
        game.updated_at = now_utc()
        game.last_scraped_at = now_utc()
        game.last_ingested_at = now_utc()
        game.scrape_version = (game.scrape_version or 0) + 1
        session.flush()

    return updated


def ingest_boxscores_via_nba_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int, int]:
    """Ingest NBA boxscores using the NBA CDN API.

    Uses direct game_id matching — the selection query already identifies
    which DB games need boxscores, so we enrich them directly without
    re-searching by team+date.

    Flow:
    1. Populate nba_game_id for games missing it (via NBA scoreboard API)
    2. Select games with nba_game_id that need boxscore data
    3. For each game: fetch boxscore → enrich game directly by ID → upsert stats

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
    from ..live.nba import NBALiveFeedClient

    # Step 1: Populate missing NBA game IDs
    populate_nba_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    session.expire_all()  # ensure select sees freshly-populated external_ids

    # Step 2: Select games for boxscore ingestion
    games = select_games_for_boxscores_nba_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "nba_boxscore_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0, 0)

    logger.info(
        "nba_boxscore_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Fetch and persist boxscores using direct game_id
    client = NBALiveFeedClient()
    games_processed = 0
    games_enriched = 0
    games_with_stats = 0

    for game_id, nba_game_id, game_date in games:
        try:
            boxscore = client.fetch_boxscore(nba_game_id)

            if not boxscore:
                logger.warning(
                    "nba_boxscore_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    nba_game_id=nba_game_id,
                )
                continue

            # Load game directly by ID — no team+date re-lookup needed
            game = session.get(db_models.SportsGame, game_id)
            if not game:
                logger.warning(
                    "nba_boxscore_game_missing",
                    run_id=run_id,
                    game_id=game_id,
                    nba_game_id=nba_game_id,
                )
                continue

            # Enrich game scores/status directly
            enriched = _enrich_game_from_boxscore(session, game, boxscore)

            # Build TeamIdentity from the game's own team records (not from CDN tricodes)
            # to ensure boxscore upserts link to the correct existing teams
            home_identity = _team_identity_from_db(session, game.home_team_id)
            away_identity = _team_identity_from_db(session, game.away_team_id)

            # Remap team identities on boxscore payloads to use DB teams
            home_tricode = boxscore.home_team.abbreviation
            for tb in boxscore.team_boxscores:
                tb.team = home_identity if tb.is_home else away_identity
            for pb in boxscore.player_boxscores:
                if pb.team.abbreviation == home_tricode:
                    pb.team = home_identity
                else:
                    pb.team = away_identity

            # Upsert team and player boxscores using the known game_id
            upsert_team_boxscores(session, game.id, boxscore.team_boxscores)

            player_stats: PlayerBoxscoreStats | None = None
            if boxscore.player_boxscores:
                player_stats = upsert_player_boxscores(
                    session, game.id, boxscore.player_boxscores
                )

            games_processed += 1
            if enriched:
                games_enriched += 1
            if player_stats and player_stats.inserted > 0:
                games_with_stats += 1

            logger.info(
                "nba_boxscore_ingested",
                run_id=run_id,
                game_id=game_id,
                nba_game_id=nba_game_id,
                enriched=enriched,
                player_stats_inserted=player_stats.inserted if player_stats else 0,
            )

        except Exception as exc:
            logger.warning(
                "nba_boxscore_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                nba_game_id=nba_game_id,
                error=str(exc),
            )
            continue

    logger.info(
        "nba_boxscore_ingestion_complete",
        run_id=run_id,
        games_processed=games_processed,
        games_enriched=games_enriched,
        games_with_stats=games_with_stats,
    )

    return (games_processed, games_enriched, games_with_stats)
