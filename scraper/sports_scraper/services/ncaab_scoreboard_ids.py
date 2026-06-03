"""NCAA scoreboard fallback game-ID population."""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..utils.datetime_utils import end_of_et_day_utc, start_of_et_day_utc


def _populate_ncaa_game_ids_from_scoreboard(
    session: Session,
    *,
    run_id: int = 0,
    start_date: date,
    end_date: date,
) -> int:
    """Populate ncaa_game_id for games that have neither cbb_game_id nor ncaa_game_id.

    Uses the NCAA scoreboard API with date-based queries to discover ncaa_game_ids.
    Matches by normalized team name. This covers conference tournament and
    postseason games that the CBB API doesn't carry.

    Returns:
        Number of games updated with NCAA game IDs.
    """
    from ..live.ncaab import NCAABLiveFeedClient
    from ..normalization import normalize_team_name

    league = session.query(db_models.SportsLeague).filter(
        db_models.SportsLeague.code == "NCAAB"
    ).first()
    if not league:
        return 0

    # Find games that have NEITHER cbb_game_id NOR ncaa_game_id
    cbb_expr = db_models.SportsGame.external_ids["cbb_game_id"].astext
    ncaa_expr = db_models.SportsGame.external_ids["ncaa_game_id"].astext

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
            or_(cbb_expr.is_(None), cbb_expr == ""),
            or_(ncaa_expr.is_(None), ncaa_expr == ""),
        )
        .all()
    )

    if not games_missing:
        return 0

    logger.info(
        "ncaab_ncaa_game_ids_missing",
        run_id=run_id,
        count=len(games_missing),
        start_date=str(start_date),
        end_date=str(end_date),
    )

    # Build team_id -> normalized name mapping
    all_teams = session.query(
        db_models.SportsTeam.id,
        db_models.SportsTeam.name,
    ).filter(
        db_models.SportsTeam.league_id == league.id,
    ).all()

    team_id_to_canonical: dict[int, str] = {}
    for team_id, team_name in all_teams:
        if team_name:
            canonical, _ = normalize_team_name("NCAAB", team_name)
            team_id_to_canonical[team_id] = canonical

    # Fetch NCAA scoreboard for each date in range
    client = NCAABLiveFeedClient()
    # Build lookup: (home_canonical, away_canonical) -> ncaa_game_id
    scoreboard_by_teams: dict[tuple[str, str], str] = {}

    current = start_date
    from datetime import timedelta
    while current <= end_date:
        try:
            scoreboard_games = client.fetch_ncaa_scoreboard(game_date=current)
            for sg in scoreboard_games:
                home_canonical, _ = normalize_team_name("NCAAB", sg.home_team_short)
                away_canonical, _ = normalize_team_name("NCAAB", sg.away_team_short)
                scoreboard_by_teams[(home_canonical, away_canonical)] = sg.ncaa_game_id
                # Also store reversed for neutral-site games
                scoreboard_by_teams[(away_canonical, home_canonical)] = sg.ncaa_game_id
            logger.info(
                "ncaab_ncaa_scoreboard_fetched",
                run_id=run_id,
                date=str(current),
                games=len(scoreboard_games),
            )
        except Exception as exc:
            logger.warning(
                "ncaab_ncaa_scoreboard_fetch_error",
                run_id=run_id,
                date=str(current),
                error=str(exc),
            )
        current += timedelta(days=1)

    if not scoreboard_by_teams:
        logger.info(
            "ncaab_ncaa_scoreboard_no_games",
            run_id=run_id,
            start_date=str(start_date),
            end_date=str(end_date),
        )
        return 0

    # Match DB games to NCAA scoreboard by team names
    updated = 0
    for game_id, _game_date, home_team_id, away_team_id in games_missing:
        home_canonical = team_id_to_canonical.get(home_team_id, "")
        away_canonical = team_id_to_canonical.get(away_team_id, "")

        if not home_canonical or not away_canonical:
            continue

        ncaa_game_id = scoreboard_by_teams.get((home_canonical, away_canonical))
        if not ncaa_game_id:
            continue

        game = session.query(db_models.SportsGame).get(game_id)
        if game:
            new_external_ids = dict(game.external_ids) if game.external_ids else {}
            new_external_ids["ncaa_game_id"] = ncaa_game_id
            game.external_ids = new_external_ids
            updated += 1
            logger.debug(
                "ncaab_ncaa_game_id_populated",
                run_id=run_id,
                game_id=game_id,
                ncaa_game_id=ncaa_game_id,
            )

    session.flush()
    logger.info(
        "ncaab_ncaa_game_ids_populated",
        run_id=run_id,
        updated=updated,
        total_missing=len(games_missing),
        scoreboard_games=len(scoreboard_by_teams) // 2,  # divide by 2 for reversed entries
    )
    return updated
