"""NCAAB game ID population and selection for boxscore ingestion.

Handles matching local games to CBB API game IDs and selecting
games that need boxscore data fetched.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..utils.datetime_utils import end_of_et_day_utc

from sqlalchemy import exists, not_, or_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..persistence.teams import _normalize_ncaab_name_for_matching  # noqa: F401
from ..utils.date_utils import season_ending_year


def populate_ncaab_game_ids(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Populate cbb_game_id for NCAAB games that don't have it.

    Matches games by cbb_team_id + game_date (UTC) to CBB API startDate (UTC).
    Both are actual start times in UTC - direct match.

    Returns:
        Number of games updated with CBB game IDs
    """
    from ..live.ncaab import NCAABLiveFeedClient

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NCAAB"
    ).first()
    if not league:
        return 0

    # Find games without cbb_game_id
    cbb_game_id_expr = db_models.SportsGame.external_ids["cbb_game_id"].astext

    games_missing_id = (
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
                cbb_game_id_expr.is_(None),
                cbb_game_id_expr == "",
            ),
        )
        .all()
    )

    if not games_missing_id:
        logger.info(
            "ncaab_game_ids_all_present",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        return 0

    logger.info(
        "ncaab_game_ids_missing",
        run_id=run_id,
        count=len(games_missing_id),
        start_date=str(start_date),
        end_date=str(end_date),
    )

    # Build team_id -> cbb_team_id mapping from external_codes
    teams = session.query(
        db_models.SportsTeam.id,
        db_models.SportsTeam.external_codes,
    ).filter(
        db_models.SportsTeam.league_id == league.id
    ).all()

    team_to_cbb_id: dict[int, int] = {}
    for team_id, ext_codes in teams:
        if ext_codes and ext_codes.get("cbb_team_id"):
            team_to_cbb_id[team_id] = int(ext_codes["cbb_team_id"])

    logger.info(
        "ncaab_team_mappings_loaded",
        run_id=run_id,
        teams_with_cbb_id=len(team_to_cbb_id),
    )

    # Fetch CBB schedule
    client = NCAABLiveFeedClient()
    season = season_ending_year(start_date)
    cbb_games = client.fetch_games(start_date, end_date, season=season)

    if not cbb_games:
        logger.info(
            "ncaab_game_ids_no_api_games",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
            season=season,
        )
        return 0

    # Build lookup by team IDs
    cbb_by_teams: dict[tuple[int, int], tuple[date, int]] = {}
    cbb_by_names: dict[tuple[str, str], tuple[date, int]] = {}

    for cg in cbb_games:
        game_day = cg.game_date.date()

        cbb_by_teams[(cg.home_team_id, cg.away_team_id)] = (game_day, cg.game_id)
        cbb_by_teams[(cg.away_team_id, cg.home_team_id)] = (game_day, cg.game_id)

        home_norm = _normalize_ncaab_name_for_matching(cg.home_team_name)
        away_norm = _normalize_ncaab_name_for_matching(cg.away_team_name)
        cbb_by_names[(home_norm, away_norm)] = (game_day, cg.game_id)
        cbb_by_names[(away_norm, home_norm)] = (game_day, cg.game_id)

    # Log sample of API team IDs for debugging
    sample_teams = set()
    for cg in cbb_games[:10]:
        sample_teams.add((cg.home_team_id, cg.home_team_name))
        sample_teams.add((cg.away_team_id, cg.away_team_name))

    logger.info(
        "ncaab_game_ids_api_games",
        run_id=run_id,
        total_api_games=len(cbb_games),
        final_games=sum(1 for cg in cbb_games if cg.status == "final"),
        sample_api_teams=list(sample_teams)[:10],
    )

    # Build team_id -> normalized team name mapping for fallback
    team_id_to_name: dict[int, str] = {}
    all_teams = session.query(
        db_models.SportsTeam.id,
        db_models.SportsTeam.name,
    ).filter(
        db_models.SportsTeam.league_id == league.id
    ).all()
    for team_id, team_name in all_teams:
        if team_name:
            team_id_to_name[team_id] = _normalize_ncaab_name_for_matching(team_name)

    # Match by team IDs + date, fallback to normalized names + date
    updated = 0
    unmatched = 0
    unmatched_reasons: dict[str, int] = {"no_team_mapping": 0, "no_api_match": 0, "time_mismatch": 0}

    for game_id, game_date, home_team_id, away_team_id in games_missing_id:
        cbb_home_id = team_to_cbb_id.get(home_team_id)
        cbb_away_id = team_to_cbb_id.get(away_team_id)

        if not game_date:
            unmatched += 1
            continue

        game_day = game_date.date()
        cbb_game_id = None

        # Try matching by team IDs first
        if cbb_home_id and cbb_away_id:
            match = cbb_by_teams.get((cbb_home_id, cbb_away_id))
            if match:
                api_date, api_game_id = match
                if abs((api_date - game_day).days) <= 1:
                    cbb_game_id = api_game_id

        # Fallback: try matching by normalized team names
        if not cbb_game_id:
            home_name = team_id_to_name.get(home_team_id, "")
            away_name = team_id_to_name.get(away_team_id, "")

            if home_name and away_name:
                match = cbb_by_names.get((home_name, away_name))
                if match:
                    api_date, api_game_id = match
                    if abs((api_date - game_day).days) <= 1:
                        cbb_game_id = api_game_id

        if cbb_game_id:
            game = session.query(db_models.SportsGame).get(game_id)
            if game:
                new_external_ids = dict(game.external_ids) if game.external_ids else {}
                new_external_ids["cbb_game_id"] = cbb_game_id
                game.external_ids = new_external_ids
                updated += 1
        else:
            unmatched += 1
            if not cbb_home_id or not cbb_away_id:
                unmatched_reasons["no_team_mapping"] += 1
            else:
                unmatched_reasons["no_api_match"] += 1

            if unmatched <= 5:
                db_home_name = team_id_to_name.get(home_team_id, "")
                db_away_name = team_id_to_name.get(away_team_id, "")
                match = cbb_by_teams.get((cbb_home_id, cbb_away_id)) if cbb_home_id and cbb_away_id else None
                logger.info(
                    "ncaab_game_unmatched_detail",
                    game_id=game_id,
                    db_game_day=str(game_day),
                    cbb_home_id=cbb_home_id,
                    cbb_away_id=cbb_away_id,
                    home_name=db_home_name,
                    away_name=db_away_name,
                    api_match_found=match is not None,
                    api_date=str(match[0]) if match else None,
                    date_diff=abs((match[0] - game_day).days) if match else None,
                )
                logger.debug(
                    "ncaab_game_unmatched_detail",
                    game_id=game_id,
                    game_day=str(game_day),
                    home_team_id=home_team_id,
                    away_team_id=away_team_id,
                    cbb_home_id=cbb_home_id,
                    cbb_away_id=cbb_away_id,
                    home_name_normalized=db_home_name if db_home_name else None,
                    away_name_normalized=db_away_name if db_away_name else None,
                )

    session.flush()
    logger.info(
        "ncaab_game_ids_populated",
        run_id=run_id,
        updated=updated,
        unmatched=unmatched,
        unmatched_reasons=unmatched_reasons,
        total_missing=len(games_missing_id),
    )
    return updated


def select_games_for_boxscores_ncaab_api(
    session: Session,
    *,
    start_date: date,
    end_date: date,
    only_missing: bool,
    updated_before: datetime | None,
) -> list[tuple[int, int, date, str, str]]:
    """Return game ids and CBB game IDs for NCAAB API boxscore ingestion.

    NCAAB boxscores are fetched via the CBB API using the CBB game ID
    stored in external_ids['cbb_game_id'].

    Args:
        session: Database session
        start_date: Start of date range
        end_date: End of date range
        only_missing: Skip games that already have boxscore data
        updated_before: Only include games with stale boxscore data

    Returns:
        List of (game_id, cbb_game_id, game_date, home_team_name, away_team_name) tuples
    """
    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NCAAB"
    ).first()
    if not league:
        return []

    cbb_game_id_expr = db_models.SportsGame.external_ids["cbb_game_id"].astext

    home_team = db_models.SportsTeam.__table__.alias("home_team")
    away_team = db_models.SportsTeam.__table__.alias("away_team")

    query = session.query(
        db_models.SportsGame.id,
        cbb_game_id_expr.label("cbb_game_id"),
        db_models.SportsGame.game_date,
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
        db_models.SportsGame.game_date >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
        db_models.SportsGame.game_date < end_of_et_day_utc(end_date),
        cbb_game_id_expr.isnot(None),
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
    for game_id, cbb_game_id, game_date, home_team_name, away_team_name in rows:
        if cbb_game_id:
            try:
                cbb_id = int(cbb_game_id)
                game_day = game_date.date() if game_date else None
                if game_day and home_team_name and away_team_name:
                    results.append((game_id, cbb_id, game_day, home_team_name, away_team_name))
            except (ValueError, TypeError):
                logger.warning(
                    "ncaab_boxscore_invalid_game_id",
                    game_id=game_id,
                    cbb_game_id=cbb_game_id,
                )
    return results
