"""Ingestion service for MLB Statcast-derived advanced stats.

Fetches pitch-level data from the MLB Stats API playByPlay endpoint,
aggregates into team-level plate discipline and quality-of-contact stats,
and upserts into the mlb_game_advanced_stats table.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger


def _safe_div(numerator: int | float, denominator: int | float) -> float | None:
    """Safe division returning None when denominator is zero."""
    if denominator == 0:
        return None
    return numerator / denominator


def ingest_advanced_stats_for_game(session: Session, game_id: int) -> dict:
    """Ingest Statcast-derived advanced stats for a single MLB game.

    Steps:
    1. Validate game exists, status=final, league=MLB, has mlb_game_pk
    2. Fetch aggregated Statcast data via MLBLiveFeedClient
    3. Compute derived percentages
    4. Upsert 2 rows (home + away) via INSERT...ON CONFLICT DO UPDATE
    5. Set game.last_advanced_stats_at

    Returns:
        Dict with ingestion result status.
    """
    game = session.query(db_models.SportsGame).get(game_id)
    if not game:
        logger.warning("mlb_adv_stats_game_not_found", game_id=game_id)
        return {"game_id": game_id, "status": "not_found"}

    if game.status != db_models.GameStatus.final.value:
        logger.info("mlb_adv_stats_skip_not_final", game_id=game_id, status=game.status)
        return {"game_id": game_id, "status": "skipped", "reason": "not_final"}

    league = session.query(db_models.SportsLeague).get(game.league_id)
    if not league or league.code != "MLB":
        logger.info("mlb_adv_stats_skip_not_mlb", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "not_mlb"}

    external_ids = game.external_ids or {}
    game_pk = external_ids.get("mlb_game_pk")
    if not game_pk:
        logger.warning("mlb_adv_stats_no_game_pk", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "no_game_pk"}

    # Fetch aggregated Statcast data
    from ..live.mlb import MLBLiveFeedClient

    client = MLBLiveFeedClient()
    aggregates = client.fetch_statcast_aggregates(int(game_pk), game_status="final")

    # Build upsert rows for home and away
    team_map = {
        "home": {"team_id": game.home_team_id, "is_home": True},
        "away": {"team_id": game.away_team_id, "is_home": False},
    }

    upserted = 0
    for side, meta in team_map.items():
        agg = aggregates[side]
        row = {
            "game_id": game_id,
            "team_id": meta["team_id"],
            "is_home": meta["is_home"],
            "total_pitches": agg.total_pitches,
            "zone_pitches": agg.zone_pitches,
            "zone_swings": agg.zone_swings,
            "zone_contact": agg.zone_contact,
            "outside_pitches": agg.outside_pitches,
            "outside_swings": agg.outside_swings,
            "outside_contact": agg.outside_contact,
            "z_swing_pct": _safe_div(agg.zone_swings, agg.zone_pitches),
            "o_swing_pct": _safe_div(agg.outside_swings, agg.outside_pitches),
            "z_contact_pct": _safe_div(agg.zone_contact, agg.zone_swings),
            "o_contact_pct": _safe_div(agg.outside_contact, agg.outside_swings),
            "balls_in_play": agg.balls_in_play,
            "total_exit_velo": agg.total_exit_velo,
            "hard_hit_count": agg.hard_hit_count,
            "barrel_count": agg.barrel_count,
            "avg_exit_velo": _safe_div(agg.total_exit_velo, agg.balls_in_play),
            "hard_hit_pct": _safe_div(agg.hard_hit_count, agg.balls_in_play),
            "barrel_pct": _safe_div(agg.barrel_count, agg.balls_in_play),
            "source": "mlb_statsapi_playbyplay",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.MLBGameAdvancedStats).values(**row)
        update_cols = {col: stmt.excluded[col] for col in row if col not in ("game_id", "team_id")}
        stmt = stmt.on_conflict_do_update(
            constraint="uq_mlb_advanced_game_team",
            set_=update_cols,
        )
        session.execute(stmt)
        upserted += 1

    # Player-level advanced stats
    player_aggregates = client.fetch_player_statcast_aggregates(int(game_pk), game_status="final")
    player_upserted = 0
    for pa in player_aggregates:
        team_id = game.home_team_id if pa.side == "home" else game.away_team_id
        is_home = pa.side == "home"
        agg = pa.stats
        row = {
            "game_id": game_id,
            "team_id": team_id,
            "is_home": is_home,
            "player_external_ref": str(pa.batter_id),
            "player_name": pa.batter_name,
            "total_pitches": agg.total_pitches,
            "zone_pitches": agg.zone_pitches,
            "zone_swings": agg.zone_swings,
            "zone_contact": agg.zone_contact,
            "outside_pitches": agg.outside_pitches,
            "outside_swings": agg.outside_swings,
            "outside_contact": agg.outside_contact,
            "z_swing_pct": _safe_div(agg.zone_swings, agg.zone_pitches),
            "o_swing_pct": _safe_div(agg.outside_swings, agg.outside_pitches),
            "z_contact_pct": _safe_div(agg.zone_contact, agg.zone_swings),
            "o_contact_pct": _safe_div(agg.outside_contact, agg.outside_swings),
            "balls_in_play": agg.balls_in_play,
            "total_exit_velo": agg.total_exit_velo,
            "hard_hit_count": agg.hard_hit_count,
            "barrel_count": agg.barrel_count,
            "avg_exit_velo": _safe_div(agg.total_exit_velo, agg.balls_in_play),
            "hard_hit_pct": _safe_div(agg.hard_hit_count, agg.balls_in_play),
            "barrel_pct": _safe_div(agg.barrel_count, agg.balls_in_play),
            "source": "mlb_statsapi_playbyplay",
            "updated_at": datetime.now(UTC),
        }
        stmt = pg_insert(db_models.MLBPlayerAdvancedStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "team_id", "player_external_ref")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_mlb_player_advanced_game_team_player",
            set_=update_cols,
        )
        session.execute(stmt)
        player_upserted += 1

    # Pitcher-level Statcast aggregates (from pitcher's perspective)
    pitcher_aggregates = client.fetch_pitcher_statcast_aggregates(int(game_pk), game_status="final")
    pitcher_upserted = 0
    for pa in pitcher_aggregates:
        team_id = game.home_team_id if pa.side == "home" else game.away_team_id
        is_home = pa.side == "home"
        agg = pa.stats
        row = {
            "game_id": game_id,
            "team_id": team_id,
            "player_external_ref": str(pa.pitcher_id),
            "player_name": pa.pitcher_name,
            "is_starter": False,
            "batters_faced": pa.total_batters_faced,
            # Statcast aggregates (from pitcher perspective)
            "zone_pitches": agg.zone_pitches,
            "zone_swings": agg.zone_swings,
            "zone_contact": agg.zone_contact,
            "outside_pitches": agg.outside_pitches,
            "outside_swings": agg.outside_swings,
            "outside_contact": agg.outside_contact,
            "balls_in_play": agg.balls_in_play,
            "total_exit_velo_against": agg.total_exit_velo,
            "hard_hit_against": agg.hard_hit_count,
            "barrel_against": agg.barrel_count,
            # Derived rates
            "whiff_rate": _safe_div(
                (agg.zone_swings + agg.outside_swings) - (agg.zone_contact + agg.outside_contact),
                agg.zone_swings + agg.outside_swings,
            ),
            "z_contact_pct": _safe_div(agg.zone_contact, agg.zone_swings),
            "chase_rate": _safe_div(agg.outside_swings, agg.outside_pitches),
            "avg_exit_velo_against": _safe_div(agg.total_exit_velo, agg.balls_in_play),
            "hard_hit_pct_against": _safe_div(agg.hard_hit_count, agg.balls_in_play),
            "barrel_pct_against": _safe_div(agg.barrel_count, agg.balls_in_play),
            "pitches_thrown": agg.total_pitches,
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.MLBPitcherGameStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "team_id", "player_external_ref")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_mlb_pitcher_game_stats_identity",
            set_=update_cols,
        )
        session.execute(stmt)
        pitcher_upserted += 1

    game.last_advanced_stats_at = datetime.now(UTC)
    session.flush()

    logger.info(
        "mlb_adv_stats_ingested",
        game_id=game_id,
        game_pk=game_pk,
        team_rows_upserted=upserted,
        player_rows_upserted=player_upserted,
        pitcher_rows_upserted=pitcher_upserted,
    )

    return {
        "game_id": game_id,
        "status": "success",
        "rows_upserted": upserted,
        "player_rows_upserted": player_upserted,
        "pitcher_rows_upserted": pitcher_upserted,
    }
