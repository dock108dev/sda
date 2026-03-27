"""Ingestion service for NBA advanced stats (derived from boxscore data).

Computes efficiency ratings, four factors, and shooting metrics from
existing team and player boxscore data already in the database.
No external API calls — reads from sports_team_boxscores and
sports_player_boxscores JSONB columns.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger


def ingest_advanced_stats_for_game(session: Session, game_id: int) -> dict:
    """Compute and persist NBA advanced stats from boxscore data.

    Steps:
    1. Validate game exists, status=final, league=NBA
    2. Load team boxscores from sports_team_boxscores
    3. Load player boxscores from sports_player_boxscores
    4. Compute four factors + efficiency for both teams
    5. Compute player advanced stats (TS%, eFG%, usage, game score)
    6. Upsert team rows (2) and player rows
    7. Set game.last_advanced_stats_at
    """
    game = session.query(db_models.SportsGame).get(game_id)
    if not game:
        logger.warning("nba_adv_stats_game_not_found", game_id=game_id)
        return {"game_id": game_id, "status": "not_found"}

    _COMPLETED = {db_models.GameStatus.final.value, db_models.GameStatus.archived.value}
    if game.status not in _COMPLETED:
        logger.info("nba_adv_stats_skip_not_final", game_id=game_id, status=game.status)
        return {"game_id": game_id, "status": "skipped", "reason": "not_final"}

    league = session.query(db_models.SportsLeague).get(game.league_id)
    if not league or league.code != "NBA":
        logger.info("nba_adv_stats_skip_not_nba", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "not_nba"}

    # Load team boxscores
    team_boxscores = (
        session.query(db_models.SportsTeamBoxscore)
        .filter(db_models.SportsTeamBoxscore.game_id == game_id)
        .all()
    )

    if len(team_boxscores) < 2:
        logger.warning("nba_adv_stats_missing_boxscores", game_id=game_id, count=len(team_boxscores))
        return {"game_id": game_id, "status": "skipped", "reason": "missing_boxscores"}

    # Identify home/away
    home_box_row = None
    away_box_row = None
    for tb in team_boxscores:
        if tb.team_id == game.home_team_id:
            home_box_row = tb
        elif tb.team_id == game.away_team_id:
            away_box_row = tb

    if not home_box_row or not away_box_row:
        logger.warning("nba_adv_stats_cant_identify_teams", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "cant_identify_teams"}

    home_box = home_box_row.stats or {}
    away_box = away_box_row.stats or {}
    home_pts = game.home_score or 0
    away_pts = game.away_score or 0

    # Compute team advanced stats
    from ..live.nba_advanced import NBAAdvancedStatsFetcher, _compute_possessions, _extract_stat

    fetcher = NBAAdvancedStatsFetcher()
    team_stats = fetcher.compute_team_advanced_stats(home_box, away_box, home_pts, away_pts)

    # Upsert team rows
    upserted = 0
    for side, meta in [("home", {"team_id": game.home_team_id, "is_home": True}),
                       ("away", {"team_id": game.away_team_id, "is_home": False})]:
        ts = team_stats[side]
        row = {
            "game_id": game_id,
            "team_id": meta["team_id"],
            "is_home": meta["is_home"],
            "off_rating": ts.get("off_rating"),
            "def_rating": ts.get("def_rating"),
            "net_rating": ts.get("net_rating"),
            "pace": ts.get("pace"),
            "pie": ts.get("pie"),
            "efg_pct": ts.get("efg_pct"),
            "ts_pct": ts.get("ts_pct"),
            "fg_pct": ts.get("fg_pct"),
            "fg3_pct": ts.get("fg3_pct"),
            "ft_pct": ts.get("ft_pct"),
            "orb_pct": ts.get("orb_pct"),
            "drb_pct": ts.get("drb_pct"),
            "reb_pct": ts.get("reb_pct"),
            "ast_pct": ts.get("ast_pct"),
            "ast_ratio": ts.get("ast_ratio"),
            "ast_tov_ratio": ts.get("ast_tov_ratio"),
            "tov_pct": ts.get("tov_pct"),
            "ft_rate": ts.get("ft_rate"),
            "contested_shots": ts.get("contested_shots"),
            "deflections": ts.get("deflections"),
            "charges_drawn": ts.get("charges_drawn"),
            "loose_balls_recovered": ts.get("loose_balls_recovered"),
            "paint_points": ts.get("paint_points"),
            "fastbreak_points": ts.get("fastbreak_points"),
            "second_chance_points": ts.get("second_chance_points"),
            "points_off_turnovers": ts.get("points_off_turnovers"),
            "bench_points": ts.get("bench_points"),
            "source": "derived_from_boxscore",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NBAGameAdvancedStats).values(**row)
        update_cols = {col: stmt.excluded[col] for col in row if col not in ("game_id", "team_id")}
        stmt = stmt.on_conflict_do_update(constraint="uq_nba_advanced_game_team", set_=update_cols)
        session.execute(stmt)
        upserted += 1

    # Compute possessions for player usage calculation
    home_fga = _extract_stat(home_box, "fg_attempted")
    home_orb = _extract_stat(home_box, "offensive_rebounds")
    home_tov = _extract_stat(home_box, "turnovers") or _extract_stat(home_box, "team_turnovers")
    home_fta = _extract_stat(home_box, "ft_attempted")
    home_poss = _compute_possessions(home_fga, home_orb, home_tov, home_fta)

    away_fga = _extract_stat(away_box, "fg_attempted")
    away_orb = _extract_stat(away_box, "offensive_rebounds")
    away_tov = _extract_stat(away_box, "turnovers") or _extract_stat(away_box, "team_turnovers")
    away_fta = _extract_stat(away_box, "ft_attempted")
    away_poss = _compute_possessions(away_fga, away_orb, away_tov, away_fta)

    # Load player boxscores
    player_boxscores = (
        session.query(db_models.SportsPlayerBoxscore)
        .filter(db_models.SportsPlayerBoxscore.game_id == game_id)
        .all()
    )

    # Build player input dicts
    player_inputs = []
    for pb in player_boxscores:
        stats = pb.stats or {}
        is_home = pb.team_id == game.home_team_id
        # Player minutes may be stored as float or under "minutes" key
        mins = stats.get("minutes")
        if mins is None:
            # Try parsing from raw_stats
            mins = stats.get("min", 0)
        player_inputs.append({
            "player_id": pb.player_external_ref,
            "player_name": pb.player_name,
            "is_home": is_home,
            "stats": {**stats, "minutes": mins, "points": stats.get("points", 0)},
        })

    home_players = [p for p in player_inputs if p["is_home"]]
    away_players = [p for p in player_inputs if not p["is_home"]]

    home_player_stats = fetcher.compute_player_advanced_stats(home_players, home_poss, 240)
    away_player_stats = fetcher.compute_player_advanced_stats(away_players, away_poss, 240)

    # Upsert player rows
    player_upserted = 0
    for ps in home_player_stats + away_player_stats:
        player_id = str(ps.get("player_id", ""))
        if not player_id or player_id == "0":
            continue

        row = {
            "game_id": game_id,
            "team_id": game.home_team_id if ps["is_home"] else game.away_team_id,
            "is_home": ps["is_home"],
            "player_external_ref": player_id,
            "player_name": ps.get("player_name", "Unknown"),
            "minutes": ps.get("minutes"),
            "off_rating": ps.get("off_rating"),
            "def_rating": ps.get("def_rating"),
            "net_rating": ps.get("net_rating"),
            "usg_pct": ps.get("usg_pct"),
            "pie": ps.get("pie"),
            "ts_pct": ps.get("ts_pct"),
            "efg_pct": ps.get("efg_pct"),
            "contested_2pt_fga": ps.get("contested_2pt_fga"),
            "contested_2pt_fgm": ps.get("contested_2pt_fgm"),
            "uncontested_2pt_fga": ps.get("uncontested_2pt_fga"),
            "uncontested_2pt_fgm": ps.get("uncontested_2pt_fgm"),
            "contested_3pt_fga": ps.get("contested_3pt_fga"),
            "contested_3pt_fgm": ps.get("contested_3pt_fgm"),
            "uncontested_3pt_fga": ps.get("uncontested_3pt_fga"),
            "uncontested_3pt_fgm": ps.get("uncontested_3pt_fgm"),
            "pull_up_fga": ps.get("pull_up_fga"),
            "pull_up_fgm": ps.get("pull_up_fgm"),
            "catch_shoot_fga": ps.get("catch_shoot_fga"),
            "catch_shoot_fgm": ps.get("catch_shoot_fgm"),
            "speed": ps.get("speed"),
            "distance": ps.get("distance"),
            "touches": ps.get("touches"),
            "time_of_possession": ps.get("time_of_possession"),
            "contested_shots": ps.get("contested_shots"),
            "deflections": ps.get("deflections"),
            "charges_drawn": ps.get("charges_drawn"),
            "loose_balls_recovered": ps.get("loose_balls_recovered"),
            "screen_assists": ps.get("screen_assists"),
            "source": "derived_from_boxscore",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NBAPlayerAdvancedStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "team_id", "player_external_ref")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nba_player_advanced_game_team_player",
            set_=update_cols,
        )
        session.execute(stmt)
        player_upserted += 1

    game.last_advanced_stats_at = datetime.now(UTC)
    session.flush()

    logger.info(
        "nba_adv_stats_ingested",
        game_id=game_id,
        team_rows=upserted,
        player_rows=player_upserted,
        source="derived_from_boxscore",
    )

    return {
        "game_id": game_id,
        "status": "success",
        "rows_upserted": upserted,
        "player_rows_upserted": player_upserted,
    }
