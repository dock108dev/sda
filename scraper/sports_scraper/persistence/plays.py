"""Play-by-play persistence utilities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy.dialects.postgresql import insert

from ..db import db_models
from ..logging import logger
from ..utils.datetime_utils import now_utc

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ..models import NormalizedPlay


def create_raw_pbp_snapshot(
    session: Session,
    game_id: int,
    plays: Sequence[NormalizedPlay],
    source: str,
    scrape_run_id: int | None = None,
) -> int | None:
    """Create a raw PBP snapshot for auditability.

    This stores the raw plays BEFORE team ID resolution, preserving
    the original data as received from the source.

    Args:
        session: Database session
        game_id: ID of the game
        plays: Raw play data
        source: Data source (e.g., 'nba_live', 'nhl_api')
        scrape_run_id: Optional scrape run ID

    Returns:
        Snapshot ID if created, None if no plays
    """
    if not plays:
        return None

    # Convert plays to JSON-serializable format
    plays_json: list[dict[str, Any]] = [
        {
            "play_index": p.play_index,
            "quarter": p.quarter,
            "game_clock": p.game_clock,
            "play_type": p.play_type,
            "team_abbreviation": p.team_abbreviation,
            "player_id": p.player_id,
            "player_name": p.player_name,
            "description": p.description,
            "home_score": p.home_score,
            "away_score": p.away_score,
            "raw_data": p.raw_data,
        }
        for p in plays
    ]

    # Compute resolution stats on raw data
    teams_with_abbrev = sum(1 for p in plays if p.team_abbreviation)
    players_with_name = sum(1 for p in plays if p.player_name)
    plays_with_score = sum(1 for p in plays if p.home_score is not None)
    clock_missing = sum(1 for p in plays if not p.game_clock)

    resolution_stats = {
        "total_plays": len(plays),
        "teams_with_abbreviation": teams_with_abbrev,
        "teams_without_abbreviation": len(plays) - teams_with_abbrev,
        "players_with_name": players_with_name,
        "players_without_name": len(plays) - players_with_name,
        "plays_with_score": plays_with_score,
        "plays_without_score": len(plays) - plays_with_score,
        "clock_missing": clock_missing,
    }

    # Check if PBPSnapshot model exists in db_models
    if not hasattr(db_models, 'PBPSnapshot'):
        logger.warning(
            "pbp_snapshot_model_missing",
            game_id=game_id,
            note="PBPSnapshot table not available; skipping snapshot creation",
        )
        return None

    try:
        snapshot = db_models.PBPSnapshot(
            game_id=game_id,
            scrape_run_id=scrape_run_id,
            snapshot_type="raw",
            source=source,
            play_count=len(plays),
            plays_json=plays_json,
            metadata_json={
                "source": source,
                "scrape_run_id": scrape_run_id,
            },
            resolution_stats=resolution_stats,
        )
        session.add(snapshot)
        session.flush()

        logger.info(
            "raw_pbp_snapshot_created",
            game_id=game_id,
            snapshot_id=snapshot.id,
            play_count=len(plays),
            source=source,
        )

        return snapshot.id
    except Exception as e:
        logger.warning(
            "raw_pbp_snapshot_failed",
            game_id=game_id,
            error=str(e),
        )
        return None


def upsert_plays(
    session: Session,
    game_id: int,
    plays: Sequence[NormalizedPlay],
    *,
    source: str = "unknown",
    scrape_run_id: int | None = None,
    create_snapshot: bool = True,
) -> int:
    """Upsert play-by-play events for a game.

    Uses PostgreSQL ON CONFLICT DO UPDATE to insert new plays or update existing
    ones with fresh data (e.g., player names resolved from roster).
    Optionally creates a raw PBP snapshot for auditability.

    Args:
        session: Database session
        game_id: ID of the game
        plays: List of normalized play events
        source: Data source (e.g., 'nba_live', 'nhl_api')
        scrape_run_id: Optional scrape run ID for tracking
        create_snapshot: Whether to create a raw PBP snapshot

    Returns:
        Number of plays processed (each play is either inserted if new or
        updated if it already exists). This equals len(plays), not the count
        of newly inserted rows.
    """
    if not plays:
        return 0

    # Create raw PBP snapshot BEFORE team resolution
    if create_snapshot:
        create_raw_pbp_snapshot(session, game_id, plays, source, scrape_run_id)

    # Get the game to look up team IDs
    game = session.query(db_models.SportsGame).filter(
        db_models.SportsGame.id == game_id
    ).first()

    if not game:
        logger.warning("upsert_plays_game_not_found", game_id=game_id)
        return 0

    # Build team abbreviation/name to ID mapping
    # For NCAAB, teams may have full names instead of abbreviations
    team_map: dict[str, int] = {}
    if game.home_team:
        if game.home_team.abbreviation:
            team_map[game.home_team.abbreviation.upper()] = game.home_team.id
        if game.home_team.name:
            team_map[game.home_team.name.upper()] = game.home_team.id
    if game.away_team:
        if game.away_team.abbreviation:
            team_map[game.away_team.abbreviation.upper()] = game.away_team.id
        if game.away_team.name:
            team_map[game.away_team.name.upper()] = game.away_team.id

    # Build CBB team ID to DB team ID mapping (for NCAAB)
    cbb_team_map: dict[int, int] = {}
    for team in [game.home_team, game.away_team]:
        if team and team.external_codes:
            cbb_id = team.external_codes.get("cbb_team_id")
            if cbb_id is not None:
                cbb_team_map[int(cbb_id)] = team.id

    # Build player external_id to player.id mapping for this league
    player_map: dict[str, int] = {}
    if hasattr(db_models, "SportsPlayer"):
        players = (
            session.query(db_models.SportsPlayer.external_id, db_models.SportsPlayer.id)
            .filter(db_models.SportsPlayer.league_id == game.league_id)
            .all()
        )
        player_map = {str(p.external_id): p.id for p in players}

    # Process each play
    for play in plays:
        # Resolve team_id - try cbb_team_id first (for NCAAB), then abbreviation/name,
        # then is_home_team flag (for NCAA API plays)
        team_id = None
        if play.raw_data and play.raw_data.get("cbb_team_id"):
            cbb_id = play.raw_data.get("cbb_team_id")
            team_id = cbb_team_map.get(int(cbb_id))
        if team_id is None and play.team_abbreviation:
            team_id = team_map.get(play.team_abbreviation.upper())
        if team_id is None and play.raw_data and play.raw_data.get("is_home_team") is not None:
            is_home = play.raw_data["is_home_team"]
            if is_home is True and game.home_team:
                team_id = game.home_team.id
            elif is_home is False and game.away_team:
                team_id = game.away_team.id

        # Resolve player_ref_id from player_id (external_id in sports_players)
        player_ref_id = None
        if play.player_id:
            player_ref_id = player_map.get(str(play.player_id))

        stmt = (
            insert(db_models.SportsGamePlay)
            .values(
                game_id=game_id,
                play_index=play.play_index,
                quarter=play.quarter,
                game_clock=play.game_clock,
                play_type=play.play_type,
                team_id=team_id,
                player_id=play.player_id,
                player_name=play.player_name,
                player_ref_id=player_ref_id,
                description=play.description,
                home_score=play.home_score,
                away_score=play.away_score,
                raw_data=play.raw_data,
                updated_at=now_utc(),
            )
            .on_conflict_do_update(
                index_elements=["game_id", "play_index"],
                set_={
                    "quarter": play.quarter,
                    "game_clock": play.game_clock,
                    "play_type": play.play_type,
                    "team_id": team_id,
                    "player_id": play.player_id,
                    "player_name": play.player_name,
                    "player_ref_id": player_ref_id,
                    "description": play.description,
                    "home_score": play.home_score,
                    "away_score": play.away_score,
                    "raw_data": play.raw_data,
                    "updated_at": now_utc(),
                },
            )
        )
        session.execute(stmt)

    # Return the number of plays processed. With ON CONFLICT DO UPDATE,
    # every play is either inserted (if new) or updated (if exists).
    # This count represents plays written to the database, not net new inserts.
    plays_processed = len(plays)
    logger.info("plays_upserted", game_id=game_id, count=plays_processed)
    if plays_processed:
        game.last_pbp_at = now_utc()

        # Set end_time if game is final and we have game_date
        # Estimate: game_date + 2.5 hours for typical NBA/NHL game
        if game.status == db_models.GameStatus.final.value and game.end_time is None:
            if game.game_date:
                from datetime import timedelta
                game.end_time = game.game_date + timedelta(hours=2, minutes=30)
                logger.info(
                    "game_end_time_estimated",
                    game_id=game_id,
                    game_date=str(game.game_date),
                    end_time=str(game.end_time),
                )

        session.flush()
    return plays_processed
