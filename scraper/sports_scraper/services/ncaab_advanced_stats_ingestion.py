"""Ingestion service for NCAAB four-factor advanced stats.

Reads existing CBB API boxscore data from the database, computes
tempo-free four-factor analytics and player advanced stats, and
upserts into the ncaab_game_advanced_stats / ncaab_player_advanced_stats
tables.

Key difference from MLB/NHL: NO external API calls. Everything is
computed from boxscore data already in sports_team_boxscores and
sports_player_boxscores.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..live.ncaab_advanced import NCAABAdvancedStatsFetcher
from ..logging import logger


def ingest_advanced_stats_for_game(session: Session, game_id: int) -> dict:
    """Ingest four-factor advanced stats for a single NCAAB game.

    Steps:
    1. Validate game exists, status=final, league=NCAAB
    2. Load team boxscores from sports_team_boxscores
    3. Load player boxscores from sports_player_boxscores
    4. Compute four factors for both teams
    5. Compute player advanced stats
    6. Upsert team rows (2) and player rows
    7. Set game.last_advanced_stats_at

    Returns:
        Dict with ingestion result status.
    """
    game = session.query(db_models.SportsGame).get(game_id)
    if not game:
        logger.warning("ncaab_adv_stats_game_not_found", game_id=game_id)
        return {"game_id": game_id, "status": "not_found"}

    _COMPLETED = {db_models.GameStatus.final.value, db_models.GameStatus.archived.value}
    if game.status not in _COMPLETED:
        logger.info("ncaab_adv_stats_skip_not_final", game_id=game_id, status=game.status)
        return {"game_id": game_id, "status": "skipped", "reason": "not_final"}

    league = session.query(db_models.SportsLeague).get(game.league_id)
    if not league or league.code != "NCAAB":
        logger.info("ncaab_adv_stats_skip_not_ncaab", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "not_ncaab"}

    # Load team boxscores
    team_boxscores = (
        session.query(db_models.SportsTeamBoxscore)
        .filter(db_models.SportsTeamBoxscore.game_id == game_id)
        .all()
    )

    if len(team_boxscores) < 2:
        logger.warning(
            "ncaab_adv_stats_missing_boxscores",
            game_id=game_id,
            boxscore_count=len(team_boxscores),
        )
        return {"game_id": game_id, "status": "skipped", "reason": "missing_boxscores"}

    # Identify home/away boxscores
    home_box_row = None
    away_box_row = None
    for tb in team_boxscores:
        if tb.team_id == game.home_team_id:
            home_box_row = tb
        elif tb.team_id == game.away_team_id:
            away_box_row = tb

    if not home_box_row or not away_box_row:
        logger.warning(
            "ncaab_adv_stats_team_mismatch",
            game_id=game_id,
            home_team_id=game.home_team_id,
            away_team_id=game.away_team_id,
        )
        return {"game_id": game_id, "status": "skipped", "reason": "team_mismatch"}

    home_box = home_box_row.stats or {}
    away_box = away_box_row.stats or {}

    # Validate we have minimum required data (handle both flat and nested CBB API formats)
    def _has_fg_data(box: dict) -> bool:
        if box.get("fieldGoalsAttempted"):
            return True
        fg = box.get("fieldGoals")
        return isinstance(fg, dict) and fg.get("attempted")

    if not _has_fg_data(home_box) and not _has_fg_data(away_box):
        logger.warning("ncaab_adv_stats_empty_boxscores", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "empty_boxscores"}

    # Compute team-level four factors
    fetcher = NCAABAdvancedStatsFetcher()
    team_stats = fetcher.compute_team_advanced_stats(home_box, away_box)

    # Build upsert rows for home and away
    team_map = {
        "home": {"team_id": game.home_team_id, "is_home": True, "stats": team_stats["home"]},
        "away": {"team_id": game.away_team_id, "is_home": False, "stats": team_stats["away"]},
    }

    upserted = 0
    for _side, meta in team_map.items():
        stats = meta["stats"]
        row = {
            "game_id": game_id,
            "team_id": meta["team_id"],
            "is_home": meta["is_home"],
            "possessions": stats.get("possessions"),
            "off_rating": stats.get("off_rating"),
            "def_rating": stats.get("def_rating"),
            "net_rating": stats.get("net_rating"),
            "pace": stats.get("pace"),
            "off_efg_pct": stats.get("off_efg_pct"),
            "off_tov_pct": stats.get("off_tov_pct"),
            "off_orb_pct": stats.get("off_orb_pct"),
            "off_ft_rate": stats.get("off_ft_rate"),
            "def_efg_pct": stats.get("def_efg_pct"),
            "def_tov_pct": stats.get("def_tov_pct"),
            "def_orb_pct": stats.get("def_orb_pct"),
            "def_ft_rate": stats.get("def_ft_rate"),
            "fg_pct": stats.get("fg_pct"),
            "three_pt_pct": stats.get("three_pt_pct"),
            "ft_pct": stats.get("ft_pct"),
            "three_pt_rate": stats.get("three_pt_rate"),
            "source": "cbb_api_boxscore_computed",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NCAABGameAdvancedStats).values(**row)
        update_cols = {col: stmt.excluded[col] for col in row if col not in ("game_id", "team_id")}
        stmt = stmt.on_conflict_do_update(
            constraint="uq_ncaab_advanced_game_team",
            set_=update_cols,
        )
        session.execute(stmt)
        upserted += 1

    # Load player boxscores
    player_boxscores = (
        session.query(db_models.SportsPlayerBoxscore)
        .filter(db_models.SportsPlayerBoxscore.game_id == game_id)
        .all()
    )

    player_upserted = 0

    # Group players by team
    home_players = []
    away_players = []
    for pb in player_boxscores:
        player_data = {
            "stats": pb.stats or {},
            "player_external_ref": pb.player_external_ref,
            "player_name": pb.player_name,
            "team_id": pb.team_id,
        }
        if pb.team_id == game.home_team_id:
            home_players.append(player_data)
        elif pb.team_id == game.away_team_id:
            away_players.append(player_data)

    # Compute and upsert player advanced stats
    for side_players, team_id, is_home, team_adv in [
        (home_players, game.home_team_id, True, team_stats["home"]),
        (away_players, game.away_team_id, False, team_stats["away"]),
    ]:
        team_possessions = team_adv.get("possessions") or 0.0
        # Estimate team minutes: 200 for regulation (5 players * 40 min)
        team_minutes = 200.0

        player_results = fetcher.compute_player_advanced_stats(
            side_players, team_possessions, team_minutes
        )

        for pr in player_results:
            if not pr.get("player_external_ref"):
                continue

            row = {
                "game_id": game_id,
                "team_id": team_id,
                "is_home": is_home,
                "player_external_ref": pr["player_external_ref"],
                "player_name": pr["player_name"],
                "minutes": pr.get("minutes"),
                "off_rating": pr.get("off_rating"),
                "usg_pct": pr.get("usg_pct"),
                "ts_pct": pr.get("ts_pct"),
                "efg_pct": pr.get("efg_pct"),
                "game_score": pr.get("game_score"),
                "points": pr.get("points"),
                "rebounds": pr.get("rebounds"),
                "assists": pr.get("assists"),
                "steals": pr.get("steals"),
                "blocks": pr.get("blocks"),
                "turnovers": pr.get("turnovers"),
                "source": "cbb_api_boxscore_computed",
                "updated_at": datetime.now(UTC),
            }

            stmt = pg_insert(db_models.NCAABPlayerAdvancedStats).values(**row)
            update_cols = {
                col: stmt.excluded[col]
                for col in row
                if col not in ("game_id", "team_id", "player_external_ref")
            }
            stmt = stmt.on_conflict_do_update(
                constraint="uq_ncaab_player_advanced_game_team_player",
                set_=update_cols,
            )
            session.execute(stmt)
            player_upserted += 1

    game.last_advanced_stats_at = datetime.now(UTC)
    session.flush()

    logger.info(
        "ncaab_adv_stats_ingested",
        game_id=game_id,
        team_rows_upserted=upserted,
        player_rows_upserted=player_upserted,
    )

    return {
        "game_id": game_id,
        "status": "success",
        "rows_upserted": upserted,
        "player_rows_upserted": player_upserted,
    }
