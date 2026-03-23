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
from ..utils.math import safe_div as _safe_div


def _parse_ip(ip_str: str) -> float:
    """Convert MLB innings-pitched notation to a float.

    MLB encodes partial innings as .1 (one-third) and .2 (two-thirds).
    E.g. "6.2" = 6⅔ innings = 6.667, "1.1" = 1⅓ = 1.333.
    """
    if not ip_str:
        return 0.0
    parts = ip_str.split(".")
    whole = int(parts[0]) if parts[0] else 0
    if len(parts) > 1 and parts[1]:
        thirds = int(parts[1])
        return whole + thirds / 3.0
    return float(whole)


def _extract_pitcher_boxscore_data(boxscore_raw: dict) -> dict[str, dict]:
    """Extract per-pitcher boxscore stats from raw MLB boxscore JSON.

    Returns {pitcher_id_str: {innings_pitched, hits, runs, earned_runs,
    walks, strikeouts, home_runs_allowed, pitches_thrown, strikes, balls,
    batters_faced, is_starter}}.
    """
    result: dict[str, dict] = {}
    teams = boxscore_raw.get("teams", {})

    for side in ("home", "away"):
        team_data = teams.get(side, {})
        pitcher_ids = team_data.get("pitchers", [])
        starter_id = pitcher_ids[0] if pitcher_ids else None
        players = team_data.get("players", {})

        for pid in pitcher_ids:
            player_key = f"ID{pid}"
            player_data = players.get(player_key, {})
            pitching = player_data.get("stats", {}).get("pitching", {})
            if not pitching:
                continue

            result[str(pid)] = {
                "innings_pitched": _parse_ip(pitching.get("inningsPitched", "0")),
                "hits": int(pitching.get("hits", 0)),
                "runs": int(pitching.get("runs", 0)),
                "earned_runs": int(pitching.get("earnedRuns", 0)),
                "walks": int(pitching.get("baseOnBalls", 0)),
                "strikeouts": int(pitching.get("strikeOuts", 0)),
                "home_runs_allowed": int(pitching.get("homeRuns", 0)),
                "pitches_thrown": int(pitching.get("numberOfPitches", 0)),
                "strikes": int(pitching.get("strikes", 0)),
                "balls": int(pitching.get("balls", 0)),
                "batters_faced": int(pitching.get("battersFaced", 0)),
                "is_starter": pid == starter_id,
            }

    return result


def _extract_player_fielding_data(boxscore_raw: dict) -> list[dict]:
    """Extract per-player fielding stats from raw MLB boxscore JSON.

    Returns list of dicts with player_id, player_name, team_side, position,
    errors, assists, putouts, and other fielding metrics.
    """
    result: list[dict] = []
    teams = boxscore_raw.get("teams", {})

    for side in ("home", "away"):
        team_data = teams.get(side, {})
        players = team_data.get("players", {})

        for _player_key, player_data in players.items():
            person = player_data.get("person", {})
            player_id = person.get("id")
            player_name = person.get("fullName", "")
            if not player_id or not player_name:
                continue

            position = player_data.get("position", {}).get("abbreviation", "")
            stats = player_data.get("stats", {})
            fielding = stats.get("fielding", {})

            if not fielding:
                continue

            # Skip players with no fielding activity
            errors = int(fielding.get("errors", 0))
            assists = int(fielding.get("assists", 0))
            putouts = int(fielding.get("putOuts", 0))

            if errors == 0 and assists == 0 and putouts == 0:
                continue

            result.append({
                "player_id": str(player_id),
                "player_name": player_name,
                "side": side,
                "position": position,
                "errors": errors,
                "assists": assists,
                "putouts": putouts,
                "innings_at_position": None,  # not available per-game from boxscore
            })

    return result




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

    _COMPLETED = {db_models.GameStatus.final.value, db_models.GameStatus.archived.value}
    if game.status not in _COMPLETED:
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

    # Fetch raw boxscore for pitcher line stats (IP, K, BB, etc.)
    boxscore_raw = client.fetch_boxscore_raw(int(game_pk), game_status="final")
    pitcher_boxscore_map: dict[str, dict] = {}
    if boxscore_raw:
        try:
            pitcher_boxscore_map = _extract_pitcher_boxscore_data(boxscore_raw)
        except Exception as exc:
            logger.warning("mlb_adv_stats_boxscore_parse_error", game_id=game_id, error=str(exc))

    pitcher_upserted = 0
    for pa in pitcher_aggregates:
        team_id = game.home_team_id if pa.side == "home" else game.away_team_id
        is_home = pa.side == "home"
        agg = pa.stats
        pitcher_id_str = str(pa.pitcher_id)
        box = pitcher_boxscore_map.get(pitcher_id_str, {})
        row = {
            "game_id": game_id,
            "team_id": team_id,
            "player_external_ref": pitcher_id_str,
            "player_name": pa.pitcher_name,
            "is_starter": box.get("is_starter", False),
            "batters_faced": box.get("batters_faced", pa.total_batters_faced),
            # Boxscore pitching line
            "innings_pitched": box.get("innings_pitched", 0.0),
            "hits": box.get("hits", 0),
            "runs": box.get("runs", 0),
            "earned_runs": box.get("earned_runs", 0),
            "walks": box.get("walks", 0),
            "strikeouts": box.get("strikeouts", 0),
            "home_runs_allowed": box.get("home_runs_allowed", 0),
            "pitches_thrown": box.get("pitches_thrown", agg.total_pitches),
            "strikes": box.get("strikes", 0),
            "balls": box.get("balls", 0),
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
            "k_rate": _safe_div(box.get("strikeouts", 0), box.get("batters_faced", 0)) if box else None,
            "bb_rate": _safe_div(box.get("walks", 0), box.get("batters_faced", 0)) if box else None,
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

    # Player fielding stats (from boxscore — per-game, same pattern as pitcher stats)
    fielding_upserted = 0
    if boxscore_raw:
        try:
            fielding_data = _extract_player_fielding_data(boxscore_raw)
            for fd in fielding_data:
                team_id = game.home_team_id if fd["side"] == "home" else game.away_team_id
                row = {
                    "game_id": game_id,
                    "team_id": team_id,
                    "player_external_ref": fd["player_id"],
                    "player_name": fd["player_name"],
                    "position": fd["position"],
                    "errors": fd["errors"],
                    "assists": fd["assists"],
                    "putouts": fd["putouts"],
                    "source": "mlb_statsapi_boxscore",
                    "updated_at": datetime.now(UTC),
                }
                stmt = pg_insert(db_models.MLBPlayerFieldingStats).values(**row)
                update_cols = {
                    col: stmt.excluded[col]
                    for col in row
                    if col not in ("game_id", "player_external_ref")
                }
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_mlb_fielding_game_player",
                    set_=update_cols,
                )
                session.execute(stmt)
                fielding_upserted += 1
        except Exception as exc:
            logger.warning("mlb_fielding_stats_error", game_id=game_id, error=str(exc))

    game.last_advanced_stats_at = datetime.now(UTC)
    session.flush()

    logger.info(
        "mlb_adv_stats_ingested",
        game_id=game_id,
        game_pk=game_pk,
        team_rows_upserted=upserted,
        player_rows_upserted=player_upserted,
        pitcher_rows_upserted=pitcher_upserted,
        fielding_rows_upserted=fielding_upserted,
    )

    return {
        "game_id": game_id,
        "status": "success",
        "rows_upserted": upserted,
        "player_rows_upserted": player_upserted,
        "pitcher_rows_upserted": pitcher_upserted,
        "fielding_rows_upserted": fielding_upserted,
    }
