"""MLB boxscore ingestion via official MLB Stats API.

This module handles boxscore data ingestion for MLB games using
the official MLB Stats API (statsapi.mlb.com).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..utils.datetime_utils import ET, end_of_et_day_utc

from sqlalchemy import exists, not_, or_
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


def populate_mlb_games_from_schedule(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Pre-populate MLB game stubs from the official MLB Schedule API.

    Ensures every MLB game exists in the database regardless of Odds API coverage.
    Uses upsert_game_stub which is idempotent — games already created by
    the Odds API won't be duplicated.

    Returns:
        Number of new games created.
    """
    from ..live.mlb import MLBLiveFeedClient
    from ..live.mlb_constants import MLB_GAME_TYPE_MAP
    from ..persistence.games import upsert_game_stub

    client = MLBLiveFeedClient()
    mlb_games = client.fetch_schedule(start_date, end_date)

    if not mlb_games:
        logger.info(
            "mlb_schedule_no_games",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        return 0

    logger.info(
        "mlb_schedule_pre_populate_start",
        run_id=run_id,
        schedule_games=len(mlb_games),
        start_date=str(start_date),
        end_date=str(end_date),
    )

    created = 0
    for mg in mlb_games:
        external_ids = {"mlb_game_pk": str(mg.game_pk)}
        season_type = MLB_GAME_TYPE_MAP.get(mg.game_type, "regular") if mg.game_type else "regular"

        try:
            _game_id, was_created = upsert_game_stub(
                session,
                league_code="MLB",
                game_date=mg.game_date,
                home_team=mg.home_team,
                away_team=mg.away_team,
                status=mg.status,
                home_score=mg.home_score,
                away_score=mg.away_score,
                venue=mg.venue,
                external_ids=external_ids,
                season_type=season_type,
            )
            if was_created:
                created += 1
        except Exception as exc:
            logger.warning(
                "mlb_schedule_stub_failed",
                run_id=run_id,
                game_pk=mg.game_pk,
                error=str(exc),
            )

    session.flush()
    logger.info(
        "mlb_schedule_pre_populate_complete",
        run_id=run_id,
        schedule_games=len(mlb_games),
        created=created,
    )
    return created


def populate_mlb_game_ids(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Populate mlb_game_pk for MLB games that don't have it.

    Fetches the MLB schedule and matches games by team + date to populate
    the external_ids['mlb_game_pk'] field needed for boxscore/PBP fetching.

    Returns:
        Number of games updated with MLB game IDs
    """
    from ..live.mlb import MLBLiveFeedClient

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "MLB"
    ).first()
    if not league:
        return 0

    # Find games without mlb_game_pk
    mlb_game_pk_expr = db_models.SportsGame.external_ids["mlb_game_pk"].astext

    games_missing_pk = (
        session.query(
            db_models.SportsGame.id,
            db_models.SportsGame.game_date,
            db_models.SportsGame.home_team_id,
            db_models.SportsGame.away_team_id,
        )
        .filter(
            db_models.SportsGame.league_id == league.id,
            db_models.SportsGame.game_date >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
            db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
            or_(
                mlb_game_pk_expr.is_(None),
                mlb_game_pk_expr == "",
            ),
        )
        .all()
    )

    if not games_missing_pk:
        logger.info(
            "mlb_game_ids_all_present",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        return 0

    logger.info(
        "mlb_game_ids_missing",
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

    # Fetch MLB schedule
    client = MLBLiveFeedClient()
    mlb_games = client.fetch_schedule(start_date, end_date)

    # Build lookup: (home_abbr, away_abbr, date) -> sorted list of game_pks.
    # Using a list prevents doubleheader collisions where the same teams play
    # twice on the same date (lower game_pk = earlier game).
    # NOTE: MLB API game_date is in UTC. Late West Coast games (e.g. 8 PM ET =
    # midnight+ UTC) have a UTC date one day ahead of the ET sports-calendar date.
    # The DB stores game_date normalised to midnight ET, so we must convert the
    # API datetime to ET before extracting the date for a correct match.
    mlb_lookup: dict[tuple[str, str, date], list[int]] = {}
    for mg in mlb_games:
        game_day_et = mg.game_date.astimezone(ET).date()
        key = (
            mg.home_team.abbreviation.upper(),
            mg.away_team.abbreviation.upper(),
            game_day_et,
        )
        mlb_lookup.setdefault(key, []).append(mg.game_pk)

    for pks in mlb_lookup.values():
        pks.sort()
        if len(pks) > 1:
            logger.info(
                "mlb_doubleheader_detected",
                run_id=run_id,
                game_pks=pks,
            )

    # Track assigned game_pks to avoid double-assignment in doubleheaders
    assigned_pks: set[int] = set()

    # Match and update
    updated = 0
    for game_id, game_date, home_team_id, away_team_id in games_missing_pk:
        home_abbr = team_id_to_abbr.get(home_team_id, "").upper()
        away_abbr = team_id_to_abbr.get(away_team_id, "").upper()
        game_day = game_date.date() if game_date else None

        if not home_abbr or not away_abbr or not game_day:
            continue

        key = (home_abbr, away_abbr, game_day)
        candidates = mlb_lookup.get(key, [])

        # Pick the first unassigned game_pk
        mlb_game_pk = next((pk for pk in candidates if pk not in assigned_pks), None)

        if mlb_game_pk:
            assigned_pks.add(mlb_game_pk)
            game = session.query(db_models.SportsGame).get(game_id)
            if game:
                new_external_ids = dict(game.external_ids) if game.external_ids else {}
                new_external_ids["mlb_game_pk"] = mlb_game_pk
                game.external_ids = new_external_ids
                updated += 1
                logger.info(
                    "mlb_game_id_populated",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                    home=home_abbr,
                    away=away_abbr,
                )

    session.flush()
    logger.info(
        "mlb_game_ids_populated",
        run_id=run_id,
        updated=updated,
        total_missing=len(games_missing_pk),
    )
    return updated


def select_games_for_boxscores_mlb_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int, date, str | None]]:
    """Return game ids, MLB game PKs, dates, and status for MLB API boxscore ingestion."""
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "MLB"
    ).first()
    if not league:
        return []

    mlb_game_pk_expr = db_models.SportsGame.external_ids["mlb_game_pk"].astext

    query = session.query(
        db_models.SportsGame.id,
        mlb_game_pk_expr.label("mlb_game_pk"),
        db_models.SportsGame.game_date,
        db_models.SportsGame.status,
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
    for game_id, mlb_game_pk, game_date, status in rows:
        if mlb_game_pk:
            try:
                mlb_pk = int(mlb_game_pk)
                game_day = game_date.date() if game_date else None
                if game_day:
                    results.append((game_id, mlb_pk, game_day, status))
            except (ValueError, TypeError):
                logger.warning(
                    "mlb_boxscore_invalid_game_pk",
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                )
    return results


def ingest_boxscores_via_mlb_api(
    session: Session,
    *,
    run_id: int,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> tuple[int, int, int]:
    """Ingest MLB boxscores using the official MLB Stats API.

    Flow:
    1. Populate mlb_game_pk for games missing it (via MLB schedule API)
    2. Select games with mlb_game_pk that need boxscore data
    3. Fetch boxscore from MLB API for each game
    4. Convert to NormalizedGame with team/player boxscores
    5. Persist via existing persist_game_payload()

    Returns:
        Tuple of (games_processed, games_enriched, games_with_stats)
    """
    from ..live.mlb import MLBLiveFeedClient

    # Step 1: Populate missing MLB game IDs
    populate_mlb_game_ids(
        session,
        run_id=run_id,
        start_date=start_date,
        end_date=end_date,
    )
    session.expire_all()

    # Step 2: Select games for boxscore ingestion
    games = select_games_for_boxscores_mlb_api(
        session,
        start_date=start_date,
        end_date=end_date,
        only_missing=only_missing,
        updated_before=updated_before,
    )

    if not games:
        logger.info(
            "mlb_boxscore_no_games_selected",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            only_missing=only_missing,
        )
        return (0, 0, 0)

    logger.info(
        "mlb_boxscore_games_selected",
        run_id=run_id,
        games=len(games),
        only_missing=only_missing,
        updated_before=str(updated_before) if updated_before else None,
    )

    # Step 3: Fetch and persist boxscores
    client = MLBLiveFeedClient()
    games_processed = 0
    games_enriched = 0
    games_with_stats = 0

    for game_id, mlb_game_pk, game_date, game_status in games:
        try:
            boxscore = client.fetch_boxscore(mlb_game_pk, game_status=game_status)

            if not boxscore:
                logger.warning(
                    "mlb_boxscore_empty_response",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                )
                continue

            normalized_game = convert_mlb_boxscore_to_normalized_game(
                boxscore, game_date
            )

            result = persist_game_payload(session, normalized_game, game_id=game_id)

            if result.game_id is not None:
                games_processed += 1
                if result.enriched:
                    games_enriched += 1
                if result.has_player_stats:
                    games_with_stats += 1

                logger.info(
                    "mlb_boxscore_ingested",
                    run_id=run_id,
                    game_id=game_id,
                    mlb_game_pk=mlb_game_pk,
                    enriched=result.enriched,
                    player_stats_inserted=result.player_stats.inserted if result.player_stats else 0,
                )

        except Exception as exc:
            logger.warning(
                "mlb_boxscore_fetch_failed",
                run_id=run_id,
                game_id=game_id,
                mlb_game_pk=mlb_game_pk,
                error=str(exc),
            )
            continue

    logger.info(
        "mlb_boxscore_ingestion_complete",
        run_id=run_id,
        games_processed=games_processed,
        games_enriched=games_enriched,
        games_with_stats=games_with_stats,
    )

    return (games_processed, games_enriched, games_with_stats)


def convert_mlb_boxscore_to_normalized_game(
    boxscore,  # MLBBoxscore from live.mlb
    game_date: date,
) -> NormalizedGame:
    """Convert MLBBoxscore to NormalizedGame for persistence."""
    identity = GameIdentification(
        league_code="MLB",
        season=season_ending_year(game_date),
        season_type="regular",
        game_date=date_to_utc_datetime(game_date),
        home_team=boxscore.home_team,
        away_team=boxscore.away_team,
        source_game_key=str(boxscore.game_pk),
    )

    return NormalizedGame(
        identity=identity,
        status="completed" if boxscore.status == "final" else boxscore.status,
        home_score=boxscore.home_score,
        away_score=boxscore.away_score,
        team_boxscores=boxscore.team_boxscores,
        player_boxscores=boxscore.player_boxscores,
    )
