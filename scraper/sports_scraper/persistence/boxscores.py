"""Boxscore persistence — public API.

Handles team and player boxscore upserts and game payload persistence.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import literal
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..models import NormalizedGame, NormalizedPlayerBoxscore, NormalizedTeamBoxscore
from ..utils.datetime_utils import now_utc
from ..utils.db_queries import get_league_id
from .boxscore_helpers import (
    GamePersistResult,
    PlayerBoxscoreStats,
    _build_player_stats,
    _build_team_stats,
    _enrich_game_with_boxscore,
    _find_game_for_boxscore,
    _validate_nhl_player_boxscore,
)
from .teams import _find_team_by_name, _upsert_team

__all__ = [
    "GamePersistResult",
    "PlayerBoxscoreStats",
    "upsert_player",
    "upsert_team_boxscores",
    "upsert_player_boxscores",
    "persist_game_payload",
]


def upsert_player(
    session: Session,
    league_id: int,
    external_id: str,
    name: str,
    position: str | None = None,
    sweater_number: int | None = None,
    team_id: int | None = None,
) -> int:
    """Upsert a player to the sports_players master table.

    Returns the player's internal ID for linking to plays.
    """
    stmt = insert(db_models.SportsPlayer).values(
        league_id=league_id,
        external_id=external_id,
        name=name,
        position=position,
        sweater_number=sweater_number,
        team_id=team_id,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["league_id", "external_id"],
        set_={
            "name": stmt.excluded.name,
            "position": stmt.excluded.position,
            "sweater_number": stmt.excluded.sweater_number,
            "team_id": stmt.excluded.team_id,
            "updated_at": now_utc(),
        },
    )
    session.execute(stmt)
    session.flush()

    # Fetch the player ID
    player = (
        session.query(db_models.SportsPlayer)
        .filter(
            db_models.SportsPlayer.league_id == league_id,
            db_models.SportsPlayer.external_id == external_id,
        )
        .first()
    )
    return player.id if player else 0


def upsert_team_boxscores(
    session: Session,
    game_id: int,
    payloads: Sequence[NormalizedTeamBoxscore],
    source: str = "sports_reference",
) -> None:
    """Upsert team boxscores for a game."""
    updated = False
    for payload in payloads:
        league_id = get_league_id(session, payload.team.league_code)
        team_id = _upsert_team(session, league_id, payload.team)
        stats = _build_team_stats(payload)
        # Use literal() for proper parameter binding (avoids SQL injection with apostrophes)
        stats_json = literal(stats, type_=JSONB)
        stmt = insert(db_models.SportsTeamBoxscore).values(
            game_id=game_id,
            team_id=team_id,
            is_home=payload.is_home,
            raw_stats_json=stats,
            source=source,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_team_boxscore_game_team",
            set_={
                "raw_stats_json": stats_json,
                "updated_at": now_utc(),
            },
            where=stmt.excluded.raw_stats_json.is_distinct_from(db_models.SportsTeamBoxscore.stats),
        )
        result = session.execute(stmt)
        if result.rowcount:
            updated = True
    if updated:
        session.query(db_models.SportsGame).filter(db_models.SportsGame.id == game_id).update(
            {db_models.SportsGame.last_ingested_at: now_utc()}
        )


def upsert_player_boxscores(
    session: Session,
    game_id: int,
    payloads: Sequence[NormalizedPlayerBoxscore],
    source: str = "sports_reference",
) -> PlayerBoxscoreStats:
    """Upsert player boxscores for a game.

    Handles errors per player and logs summary statistics.
    NHL rows are validated before insertion - invalid rows are rejected and logged.

    Returns:
        PlayerBoxscoreStats with counts of inserted, rejected, and errored players.
    """
    if not payloads:
        return PlayerBoxscoreStats()

    inserted_count = 0
    rejected_count = 0
    error_count = 0

    updated = False
    for payload in payloads:
        # Pre-insert validation for NHL (rejects broken rows before DB)
        rejection_reason = _validate_nhl_player_boxscore(payload, game_id)
        if rejection_reason:
            rejected_count += 1
            continue  # Skip invalid row

        try:
            league_id = get_league_id(session, payload.team.league_code)
            team_id = _upsert_team(session, league_id, payload.team)

            # Upsert to sports_players master table (for linking PBP events)
            if payload.player_id and payload.player_name:
                upsert_player(
                    session,
                    league_id=league_id,
                    external_id=payload.player_id,
                    name=payload.player_name,
                    position=payload.position,
                    sweater_number=payload.sweater_number,
                    team_id=team_id,
                )

            stats = _build_player_stats(payload)
            # Use literal() for proper parameter binding (avoids SQL injection with apostrophes)
            stats_json = literal(stats, type_=JSONB)
            stmt = insert(db_models.SportsPlayerBoxscore).values(
                game_id=game_id,
                team_id=team_id,
                player_external_ref=payload.player_id,
                player_name=payload.player_name,
                raw_stats_json=stats,
                source=source,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_player_boxscore_identity",
                set_={
                    "raw_stats_json": stats_json,
                    "updated_at": now_utc(),
                },
                where=stmt.excluded.raw_stats_json.is_distinct_from(db_models.SportsPlayerBoxscore.stats),
            )
            result = session.execute(stmt)
            if result.rowcount:
                updated = True
            inserted_count += 1
        except Exception as exc:
            logger.error(
                "player_boxscore_upsert_failed",
                game_id=game_id,
                player_name=payload.player_name,
                error=str(exc),
                exc_info=True,
            )
            error_count += 1

    logger.info(
        "player_boxscores_upsert_complete",
        game_id=game_id,
        inserted_count=inserted_count,
        rejected_count=rejected_count,
        error_count=error_count,
    )
    if updated:
        session.query(db_models.SportsGame).filter(db_models.SportsGame.id == game_id).update(
            {db_models.SportsGame.last_ingested_at: now_utc()}
        )

    return PlayerBoxscoreStats(
        inserted=inserted_count,
        rejected=rejected_count,
        errors=error_count,
    )


def persist_game_payload(
    session: Session,
    payload: NormalizedGame,
    *,
    game_id: int | None = None,
) -> GamePersistResult:
    """Persist boxscore data by enriching an existing game record.

    ENRICHMENT-ONLY: This function does NOT create games. Games must already exist
    in the database. If ``game_id`` is provided the lookup is a direct primary-key
    fetch; otherwise the game is matched by league + teams + date window.

    Returns GamePersistResult with game_id=None if no matching game found.
    """
    if game_id is not None:
        game = session.query(db_models.SportsGame).get(game_id)
        if game is None:
            logger.warning(
                "boxscore_game_id_not_found",
                game_id=game_id,
                source_game_key=payload.identity.source_game_key,
            )
            return GamePersistResult(game_id=None, enriched=False)
    else:
        league_id = get_league_id(session, payload.identity.league_code)
        home_team_id = _find_team_by_name(
            session, league_id,
            payload.identity.home_team.name,
            payload.identity.home_team.abbreviation,
        )
        away_team_id = _find_team_by_name(
            session, league_id,
            payload.identity.away_team.name,
            payload.identity.away_team.abbreviation,
        )

        if home_team_id is None or away_team_id is None:
            logger.warning(
                "boxscore_team_not_found",
                league=payload.identity.league_code,
                home_team=payload.identity.home_team.name,
                away_team=payload.identity.away_team.name,
                home_team_found=home_team_id is not None,
                away_team_found=away_team_id is not None,
                game_date=str(payload.identity.game_date.date()),
                source_game_key=payload.identity.source_game_key,
            )
            return GamePersistResult(game_id=None, enriched=False)

        game = _find_game_for_boxscore(
            session, league_id, home_team_id, away_team_id, payload.identity.game_date
        )

        if game is None:
            logger.warning(
                "boxscore_game_not_found",
                league=payload.identity.league_code,
                home_team=payload.identity.home_team.name,
                away_team=payload.identity.away_team.name,
                game_date=str(payload.identity.game_date.date()),
                source_game_key=payload.identity.source_game_key,
            )
            return GamePersistResult(game_id=None, enriched=False)

    # Enrich existing game with boxscore data
    enriched = _enrich_game_with_boxscore(session, game, payload)

    # Attach team boxscores
    upsert_team_boxscores(session, game.id, payload.team_boxscores)

    logger.info(
        "persist_game_payload",
        game_id=game.id,
        game_key=payload.identity.source_game_key,
        enriched=enriched,
        previous_status=game.status,
        team_boxscores_count=len(payload.team_boxscores),
        player_boxscores_count=len(payload.player_boxscores) if payload.player_boxscores else 0,
    )

    # Attach player boxscores
    player_stats: PlayerBoxscoreStats | None = None
    if payload.player_boxscores:
        try:
            logger.info("persisting_player_boxscores", game_id=game.id, count=len(payload.player_boxscores))
            player_stats = upsert_player_boxscores(session, game.id, payload.player_boxscores)
        except Exception as exc:
            logger.error(
                "failed_to_persist_player_boxscores_for_game",
                game_id=game.id,
                game_key=payload.identity.source_game_key,
                error=str(exc),
                exc_info=True,
            )
    else:
        logger.warning("no_player_boxscores_to_persist", game_id=game.id, game_key=payload.identity.source_game_key)

    return GamePersistResult(game_id=game.id, enriched=enriched, player_stats=player_stats)
