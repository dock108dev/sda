"""Ingestion service for NFL nflverse-derived advanced stats.

Fetches play-by-play data from nflverse via nflreadpy, aggregates into
team-level and player-level EPA/WPA/CPOE stats, and upserts into the
nfl_game_advanced_stats and nfl_player_advanced_stats tables.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..utils.math import safe_float as _safe_float


def ingest_advanced_stats_for_game(session: Session, game_id: int) -> dict:
    """Ingest nflverse-derived advanced stats for a single NFL game.

    Steps:
    1. Validate game exists, status=final/archived, league=NFL
    2. Determine season from game.season
    3. Fetch and filter plays via nflreadpy (matches by date + teams)
    4. Aggregate team + player stats
    5. Upsert team rows (2) and player rows
    6. Set game.last_advanced_stats_at

    Returns:
        Dict with ingestion result status.
    """
    game = session.query(db_models.SportsGame).get(game_id)
    if not game:
        logger.warning("nfl_adv_stats_game_not_found", game_id=game_id)
        return {"game_id": game_id, "status": "not_found"}

    _COMPLETED = {db_models.GameStatus.final.value, db_models.GameStatus.archived.value}
    if game.status not in _COMPLETED:
        logger.info("nfl_adv_stats_skip_not_final", game_id=game_id, status=game.status)
        return {"game_id": game_id, "status": "skipped", "reason": "not_final"}

    league = session.query(db_models.SportsLeague).get(game.league_id)
    if not league or league.code != "NFL":
        logger.info("nfl_adv_stats_skip_not_nfl", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "not_nfl"}

    external_ids = game.external_ids or {}
    espn_game_id = external_ids.get("espn_game_id")
    season = game.season

    # Resolve team abbreviations for nflverse matching
    home_team = session.query(db_models.SportsTeam).get(game.home_team_id)
    away_team = session.query(db_models.SportsTeam).get(game.away_team_id)
    home_abbr = home_team.abbreviation if home_team else None
    away_abbr = away_team.abbreviation if away_team else None
    game_date_str = str(game.game_date.date()) if game.game_date else None

    # Fetch plays from nflverse (matches by date + teams, not ESPN ID)
    from ..live.nfl_advanced import NFLAdvancedStatsFetcher

    fetcher = NFLAdvancedStatsFetcher()
    plays = fetcher.fetch_game_plays(
        int(espn_game_id) if espn_game_id else 0,
        season,
        home_abbr=home_abbr,
        away_abbr=away_abbr,
        game_date=game_date_str,
    )

    if not plays:
        logger.warning(
            "nfl_adv_stats_no_plays",
            game_id=game_id, espn_game_id=espn_game_id,
            home_abbr=home_abbr, away_abbr=away_abbr, game_date=game_date_str,
        )
        return {"game_id": game_id, "status": "skipped", "reason": "no_plays"}

    # Aggregate team stats
    team_aggregates = fetcher.aggregate_team_stats(plays)

    # Build upsert rows for home and away
    team_map = {
        "home": {"team_id": game.home_team_id, "is_home": True},
        "away": {"team_id": game.away_team_id, "is_home": False},
    }

    upserted = 0
    for side, meta in team_map.items():
        agg = team_aggregates.get(side, {})
        if not agg:
            continue

        row = {
            "game_id": game_id,
            "team_id": meta["team_id"],
            "is_home": meta["is_home"],
            "total_epa": _safe_float(agg.get("total_epa")),
            "pass_epa": _safe_float(agg.get("pass_epa")),
            "rush_epa": _safe_float(agg.get("rush_epa")),
            "epa_per_play": _safe_float(agg.get("epa_per_play")),
            "total_wpa": _safe_float(agg.get("total_wpa")),
            "success_rate": _safe_float(agg.get("success_rate")),
            "pass_success_rate": _safe_float(agg.get("pass_success_rate")),
            "rush_success_rate": _safe_float(agg.get("rush_success_rate")),
            "explosive_play_rate": _safe_float(agg.get("explosive_play_rate")),
            "avg_cpoe": _safe_float(agg.get("avg_cpoe")),
            "avg_air_yards": _safe_float(agg.get("avg_air_yards")),
            "avg_yac": _safe_float(agg.get("avg_yac")),
            "total_plays": agg.get("total_plays"),
            "pass_plays": agg.get("pass_plays"),
            "rush_plays": agg.get("rush_plays"),
            "source": "nflverse",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NFLGameAdvancedStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "team_id")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nfl_advanced_game_team",
            set_=update_cols,
        )
        session.execute(stmt)
        upserted += 1

    # Player-level advanced stats
    player_aggregates = fetcher.aggregate_player_stats(plays)
    player_upserted = 0
    for pa in player_aggregates:
        is_home = pa.get("is_home", False)
        team_id = game.home_team_id if is_home else game.away_team_id

        row = {
            "game_id": game_id,
            "team_id": team_id,
            "is_home": is_home,
            "player_external_ref": pa["player_external_ref"],
            "player_name": pa["player_name"],
            "player_role": pa["player_role"],
            "total_epa": _safe_float(pa.get("total_epa")),
            "epa_per_play": _safe_float(pa.get("epa_per_play")),
            "pass_epa": _safe_float(pa.get("pass_epa")),
            "rush_epa": _safe_float(pa.get("rush_epa")),
            "receiving_epa": _safe_float(pa.get("receiving_epa")),
            "cpoe": _safe_float(pa.get("cpoe")),
            "air_epa": _safe_float(pa.get("air_epa")),
            "yac_epa": _safe_float(pa.get("yac_epa")),
            "air_yards": _safe_float(pa.get("air_yards")),
            "total_wpa": _safe_float(pa.get("total_wpa")),
            "success_rate": _safe_float(pa.get("success_rate")),
            "plays": pa.get("plays"),
            "source": "nflverse",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NFLPlayerAdvancedStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "team_id", "player_external_ref", "player_role")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nfl_player_advanced_game_team_player_role",
            set_=update_cols,
        )
        session.execute(stmt)
        player_upserted += 1

    game.last_advanced_stats_at = datetime.now(UTC)
    session.flush()

    logger.info(
        "nfl_adv_stats_ingested",
        game_id=game_id,
        espn_game_id=espn_game_id,
        team_rows_upserted=upserted,
        player_rows_upserted=player_upserted,
    )

    return {
        "game_id": game_id,
        "status": "success",
        "rows_upserted": upserted,
        "player_rows_upserted": player_upserted,
    }
