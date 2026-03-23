"""NFL boxscore ingestion via ESPN API.

Fetches boxscores for NFL games using the ESPN summary endpoint,
converts to NormalizedGame format, and persists via the shared
persist_game_payload function.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import and_, exists, not_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..persistence import persist_game_payload
from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc, to_et_date


def populate_nfl_games_from_schedule(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Create NFL game stubs from the ESPN schedule API.

    This is the NFL equivalent of MLB's populate_mlb_games_from_schedule.
    Creates game rows for any games found on ESPN that don't exist in the DB yet.
    """
    from ..live.nfl import NFLLiveFeedClient
    from ..persistence.games import upsert_game_stub

    client = NFLLiveFeedClient()
    schedule_games = client.fetch_schedule(start_date, end_date)

    created = 0
    for game in schedule_games:
        # Skip preseason
        if game.season_type == "preseason":
            continue

        try:
            _game_id, was_created = upsert_game_stub(
                session,
                league_code="NFL",
                game_date=game.game_date,
                home_team=game.home_team,
                away_team=game.away_team,
                status=game.status,
                home_score=game.home_score,
                away_score=game.away_score,
                external_ids={"espn_game_id": game.game_id},
                season_type=game.season_type or "regular",
            )
            if was_created:
                created += 1
        except Exception as exc:
            logger.warning(
                "nfl_schedule_stub_failed",
                espn_game_id=game.game_id,
                error=str(exc),
            )
            continue

    if created:
        session.commit()
    logger.info("nfl_games_from_schedule", run_id=run_id, created=created, total=len(schedule_games))
    return created


def populate_nfl_game_ids(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Populate espn_game_id for NFL games that don't have it.

    Fetches the ESPN scoreboard and matches games by team + date
    to populate external_ids['espn_game_id'].
    """
    from ..live.nfl import NFLLiveFeedClient

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NFL"
    ).first()
    if not league:
        return 0

    # Find games missing espn_game_id
    games_missing = (
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
        )
        .all()
    )

    # Filter to those without espn_game_id
    games_needing_ids = []
    for game_id, game_date, home_id, away_id in games_missing:
        game = session.get(db_models.SportsGame, game_id)
        if game and not (game.external_ids or {}).get("espn_game_id"):
            games_needing_ids.append((game_id, game_date, home_id, away_id))

    if not games_needing_ids:
        logger.info("nfl_game_ids_all_present", run_id=run_id)
        return 0

    # Fetch schedule from ESPN
    client = NFLLiveFeedClient()
    schedule_games = client.fetch_schedule(start_date, end_date)

    # Build team abbreviation lookup
    team_abbrs = {}
    for team in session.query(db_models.SportsTeam).filter(
        db_models.SportsTeam.league_id == league.id
    ).all():
        if team.abbreviation:
            team_abbrs[team.id] = team.abbreviation.upper()

    updated = 0
    for game_id, game_date, home_id, away_id in games_needing_ids:
        home_abbr = team_abbrs.get(home_id, "")
        away_abbr = team_abbrs.get(away_id, "")
        game_day = to_et_date(game_date) if game_date else None
        if not game_day or not home_abbr:
            continue

        for sg in schedule_games:
            # Match on teams AND date to avoid wrong assignment when
            # the same matchup appears multiple times in the date range
            sg_day = to_et_date(sg.game_date) if sg.game_date else None
            if (sg.home_team.abbreviation.upper() == home_abbr
                    and sg.away_team.abbreviation.upper() == away_abbr
                    and sg_day == game_day):
                game = session.get(db_models.SportsGame, game_id)
                if game:
                    ext = dict(game.external_ids or {})
                    ext["espn_game_id"] = sg.game_id
                    game.external_ids = ext
                    updated += 1
                break

    if updated:
        session.flush()
    logger.info("nfl_game_ids_populated", run_id=run_id, updated=updated)
    return updated


def select_games_for_boxscores_nfl_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int, date, str]]:
    """Select NFL games needing boxscore ingestion."""
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NFL"
    ).first()
    if not league:
        return []

    espn_id_expr = db_models.SportsGame.external_ids["espn_game_id"].astext

    query = session.query(
        db_models.SportsGame.id,
        espn_id_expr.label("espn_game_id"),
        db_models.SportsGame.game_date,
        db_models.SportsGame.status,
    ).filter(
        db_models.SportsGame.league_id == league.id,
        db_models.SportsGame.game_date >= start_of_et_day_utc(start_date),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
    )

    if only_missing:
        has_team_box = exists().where(
            db_models.SportsTeamBoxscore.game_id == db_models.SportsGame.id
        )
        has_player_box = exists().where(
            db_models.SportsPlayerBoxscore.game_id == db_models.SportsGame.id
        )
        query = query.filter(not_(and_(has_team_box, has_player_box)))

    rows = query.all()
    results = []
    for game_id, espn_game_id, game_date, status in rows:
        if espn_game_id:
            try:
                results.append((game_id, int(espn_game_id), game_date, status or "final"))
            except (ValueError, TypeError):
                pass
    return results


def ingest_boxscores_via_nfl_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int, int, int]:
    """Ingest NFL boxscores using the ESPN API.

    Returns (games_processed, games_enriched, games_with_stats, errors).
    """
    from ..live.nfl import NFLLiveFeedClient
    from ..models import (
        GameIdentification,
        NormalizedGame,
        NormalizedPlayerBoxscore,
        NormalizedTeamBoxscore,
    )

    # Step 0: Create game stubs from ESPN schedule (like MLB)
    populate_nfl_games_from_schedule(session, run_id=run_id, start_date=start_date, end_date=end_date)
    session.expire_all()

    # Step 1: Populate missing ESPN game IDs (for games created by other paths)
    populate_nfl_game_ids(session, run_id=run_id, start_date=start_date, end_date=end_date)
    session.expire_all()

    # Step 2: Select games
    games = select_games_for_boxscores_nfl_api(
        session, start_date=start_date, end_date=end_date,
        only_missing=only_missing, updated_before=updated_before,
    )

    if not games:
        logger.info("nfl_boxscore_no_games", run_id=run_id)
        return (0, 0, 0, 0)

    logger.info("nfl_boxscore_games_selected", run_id=run_id, count=len(games))

    # Step 3: Fetch and persist
    client = NFLLiveFeedClient()
    processed = 0
    enriched = 0
    with_stats = 0
    errors = 0

    for game_id, espn_game_id, game_date, _game_status in games:
        try:
            boxscore = client.fetch_boxscore(espn_game_id)
            if not boxscore:
                continue

            # Build NormalizedGame from ESPN boxscore
            identity = GameIdentification(
                league_code="NFL",
                season=game_date.year if game_date else 2025,
                game_date=game_date,
                home_team=boxscore.home_team,
                away_team=boxscore.away_team,
                source_game_key=str(espn_game_id),
            )

            team_boxscores = [
                NormalizedTeamBoxscore(
                    team=tb.team, is_home=tb.is_home, points=tb.points,
                    raw_stats=tb.raw_stats,
                )
                for tb in boxscore.team_boxscores
            ] if boxscore.team_boxscores else []

            player_boxscores = [
                NormalizedPlayerBoxscore(
                    player_id=pb.player_id, player_name=pb.player_name,
                    team=pb.team, player_role=pb.player_role,
                    position=pb.position, raw_stats=pb.raw_stats,
                )
                for pb in boxscore.player_boxscores
            ] if boxscore.player_boxscores else []

            normalized = NormalizedGame(
                identity=identity,
                home_score=boxscore.home_score,
                away_score=boxscore.away_score,
                status=boxscore.status,
                venue=None,
                team_boxscores=team_boxscores,
                player_boxscores=player_boxscores,
            )

            result = persist_game_payload(session, normalized, game_id=game_id)
            session.commit()

            if result.game_id is not None:
                processed += 1
                if result.enriched:
                    enriched += 1
                if result.has_player_stats:
                    with_stats += 1

            logger.info(
                "nfl_boxscore_ingested", run_id=run_id,
                game_id=game_id, espn_game_id=espn_game_id,
                enriched=result.enriched if result.game_id else False,
            )

        except Exception as exc:
            session.rollback()
            errors += 1
            logger.warning(
                "nfl_boxscore_failed", run_id=run_id,
                game_id=game_id, espn_game_id=espn_game_id,
                error=str(exc),
            )
            continue

    return (processed, enriched, with_stats, errors)
