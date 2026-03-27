"""Ingestion service for NHL MoneyPuck-derived advanced stats.

Fetches shot-level data from MoneyPuck CSV files, aggregates into
team-level, skater-level, and goalie-level advanced stats, and upserts
into the corresponding database tables.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..db import db_models
from ..logging import logger
from ..utils.math import safe_div as _safe_div
from ..utils.math import safe_pct as _safe_pct


def ingest_advanced_stats_for_game(session: Session, game_id: int) -> dict:
    """Ingest MoneyPuck-derived advanced stats for a single NHL game.

    Steps:
    1. Validate game exists, status=final, league=NHL, has nhl_game_pk
    2. Determine season from game.season
    3. Fetch and filter shots for this game
    4. Aggregate team-level, skater-level, goalie-level
    5. Upsert all 3 tables
    6. Set game.last_advanced_stats_at

    Returns:
        Dict with ingestion result status.
    """
    game = session.query(db_models.SportsGame).get(game_id)
    if not game:
        logger.warning("nhl_adv_stats_game_not_found", game_id=game_id)
        return {"game_id": game_id, "status": "not_found"}

    _COMPLETED = {db_models.GameStatus.final.value, db_models.GameStatus.archived.value}
    if game.status not in _COMPLETED:
        logger.info("nhl_adv_stats_skip_not_final", game_id=game_id, status=game.status)
        return {"game_id": game_id, "status": "skipped", "reason": "not_final"}

    league = session.query(db_models.SportsLeague).get(game.league_id)
    if not league or league.code != "NHL":
        logger.info("nhl_adv_stats_skip_not_nhl", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "not_nhl"}

    external_ids = game.external_ids or {}
    nhl_game_pk = external_ids.get("nhl_game_pk")
    if not nhl_game_pk:
        logger.warning("nhl_adv_stats_no_game_pk", game_id=game_id)
        return {"game_id": game_id, "status": "skipped", "reason": "no_game_pk"}

    season = game.season

    # Fetch shot data from MoneyPuck
    from ..live.nhl_advanced import NHLAdvancedStatsFetcher

    fetcher = NHLAdvancedStatsFetcher()
    try:
        shots = fetcher.fetch_game_shots(int(nhl_game_pk), season)
    except Exception as exc:
        logger.error(
            "nhl_adv_stats_fetch_failed",
            game_id=game_id,
            nhl_game_pk=nhl_game_pk,
            season=season,
            error=str(exc),
        )
        raise

    if not shots:
        logger.warning("nhl_adv_stats_no_shots", game_id=game_id, nhl_game_pk=nhl_game_pk)
        return {"game_id": game_id, "status": "skipped", "reason": "no_shot_data"}

    # Determine home team abbreviation from the first home-team shot
    home_team_abbrev = ""
    for shot in shots:
        if shot.get("isHomeTeam") == "1":
            home_team_abbrev = shot.get("team", "")
            break

    # ---- Team-level aggregation ----
    team_aggregates = fetcher.aggregate_team_stats(shots, home_team_abbrev)

    team_map = {
        "home": {"team_id": game.home_team_id, "is_home": True},
        "away": {"team_id": game.away_team_id, "is_home": False},
    }

    team_upserted = 0
    for side, meta in team_map.items():
        agg = team_aggregates[side]

        # Corsi = SOG + missed + blocked (for the shooting team)
        corsi_for = agg.shots_on_goal + agg.missed_shots + agg.blocked_shots
        corsi_against = agg.shots_on_goal_against + agg.missed_shots_against + agg.blocked_shots_against
        # Fenwick = SOG + missed (no blocked)
        fenwick_for = agg.shots_on_goal + agg.missed_shots
        fenwick_against = agg.shots_on_goal_against + agg.missed_shots_against

        # Shooting and save percentages
        shooting_pct = _safe_pct(agg.goals, agg.shots_on_goal)
        save_pct_val = _safe_div(
            agg.shots_on_goal_against - agg.goals_against,
            agg.shots_on_goal_against,
        )
        save_pct_100 = save_pct_val * 100 if save_pct_val is not None else None
        pdo = None
        if shooting_pct is not None and save_pct_100 is not None:
            pdo = shooting_pct + save_pct_100

        row = {
            "game_id": game_id,
            "team_id": meta["team_id"],
            "is_home": meta["is_home"],
            # xGoals
            "xgoals_for": round(agg.xgoals_for, 3),
            "xgoals_against": round(agg.xgoals_against_total, 3),
            "xgoals_pct": _safe_pct(agg.xgoals_for, agg.xgoals_for + agg.xgoals_against_total),
            # Possession
            "corsi_for": corsi_for,
            "corsi_against": corsi_against,
            "corsi_pct": _safe_pct(corsi_for, corsi_for + corsi_against),
            "fenwick_for": fenwick_for,
            "fenwick_against": fenwick_against,
            "fenwick_pct": _safe_pct(fenwick_for, fenwick_for + fenwick_against),
            # Shooting
            "shots_for": agg.shots_on_goal,
            "shots_against": agg.shots_on_goal_against,
            "shooting_pct": shooting_pct,
            "save_pct": save_pct_100,
            "pdo": pdo,
            # Danger zones
            "high_danger_shots_for": agg.high_danger_shots,
            "high_danger_goals_for": agg.high_danger_goals,
            "high_danger_shots_against": agg.high_danger_shots_against,
            "high_danger_goals_against": agg.high_danger_goals_against,
            # Metadata
            "source": "moneypuck_csv",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NHLGameAdvancedStats).values(**row)
        update_cols = {col: stmt.excluded[col] for col in row if col not in ("game_id", "team_id")}
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nhl_advanced_game_team",
            set_=update_cols,
        )
        session.execute(stmt)
        team_upserted += 1

    # ---- Skater-level aggregation ----
    skater_aggregates = fetcher.aggregate_skater_stats(shots)

    # Cross-reference boxscore data for TOI and assists (MoneyPuck CSV lacks these)
    boxscore_lookup = _build_boxscore_lookup(session, game_id)

    skater_upserted = 0
    for sa in skater_aggregates:
        # Determine team_id from the team abbreviation
        is_home = sa.is_home
        team_id = game.home_team_id if is_home else game.away_team_id

        # Enrich with TOI + assists from boxscore
        box = boxscore_lookup.get(sa.player_id, {})
        toi = box.get("toi_minutes")
        assists = box.get("assists", 0)
        points = (sa.goals or 0) + assists

        # Compute per-60 rates when TOI is available
        goals_per_60 = _per_60(sa.goals, toi)
        assists_per_60 = _per_60(assists, toi)
        points_per_60 = _per_60(points, toi)
        shots_per_60 = _per_60(sa.shots, toi)
        game_score = _compute_game_score(
            sa.goals, assists, sa.shots,
            box.get("blocked_shots", 0),
        )

        row = {
            "game_id": game_id,
            "team_id": team_id,
            "is_home": is_home,
            "player_external_ref": sa.player_id,
            "player_name": sa.player_name,
            # TOI
            "toi_minutes": toi,
            # xGoals
            "xgoals_for": round(sa.xgoals_for, 3),
            "xgoals_against": round(sa.xgoals_against, 3),
            "on_ice_xgoals_pct": _safe_pct(sa.xgoals_for, sa.xgoals_for + sa.xgoals_against),
            # Shots
            "shots": sa.shots,
            "goals": sa.goals,
            "shooting_pct": _safe_pct(sa.goals, sa.shots),
            # Per-60 rates (enriched from boxscore TOI)
            "goals_per_60": goals_per_60,
            "assists_per_60": assists_per_60,
            "points_per_60": points_per_60,
            "shots_per_60": shots_per_60,
            "game_score": game_score,
            "source": "moneypuck_csv",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NHLSkaterAdvancedStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "team_id", "player_external_ref")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nhl_skater_advanced_game_team_player",
            set_=update_cols,
        )
        session.execute(stmt)
        skater_upserted += 1

    # ---- Goalie-level aggregation ----
    goalie_aggregates = fetcher.aggregate_goalie_stats(shots)

    goalie_upserted = 0
    for ga in goalie_aggregates:
        # Goalie team_id: goalie is_home is opposite of shooter
        team_id = game.home_team_id if ga.is_home else game.away_team_id

        # Goals saved above expected: xGA - GA (positive = good)
        gsae = round(ga.xgoals_against - ga.goals_against, 3)

        # Danger zone save percentages
        high_danger_save_pct = _safe_pct(
            ga.high_danger_shots - ga.high_danger_goals,
            ga.high_danger_shots,
        )
        medium_danger_save_pct = _safe_pct(
            ga.medium_danger_shots - ga.medium_danger_goals,
            ga.medium_danger_shots,
        )
        low_danger_save_pct = _safe_pct(
            ga.low_danger_shots - ga.low_danger_goals,
            ga.low_danger_shots,
        )

        row = {
            "game_id": game_id,
            "player_external_ref": ga.player_id,
            "team_id": team_id,
            "is_home": ga.is_home,
            "player_name": ga.player_name,
            # Core
            "xgoals_against": round(ga.xgoals_against, 3),
            "goals_against": ga.goals_against,
            "goals_saved_above_expected": gsae,
            "save_pct": _safe_pct(
                ga.shots_against - ga.goals_against,
                ga.shots_against,
            ),
            # Danger zone saves
            "high_danger_save_pct": high_danger_save_pct,
            "medium_danger_save_pct": medium_danger_save_pct,
            "low_danger_save_pct": low_danger_save_pct,
            "shots_against": ga.shots_against,
            "source": "moneypuck_csv",
            "updated_at": datetime.now(UTC),
        }

        stmt = pg_insert(db_models.NHLGoalieAdvancedStats).values(**row)
        update_cols = {
            col: stmt.excluded[col]
            for col in row
            if col not in ("game_id", "player_external_ref")
        }
        stmt = stmt.on_conflict_do_update(
            constraint="uq_nhl_goalie_advanced_game_player",
            set_=update_cols,
        )
        session.execute(stmt)
        goalie_upserted += 1

    # Mark game as having advanced stats
    game.last_advanced_stats_at = datetime.now(UTC)
    session.flush()

    logger.info(
        "nhl_adv_stats_ingested",
        game_id=game_id,
        nhl_game_pk=nhl_game_pk,
        season=season,
        team_rows_upserted=team_upserted,
        skater_rows_upserted=skater_upserted,
        goalie_rows_upserted=goalie_upserted,
    )

    return {
        "game_id": game_id,
        "status": "success",
        "team_rows_upserted": team_upserted,
        "skater_rows_upserted": skater_upserted,
        "goalie_rows_upserted": goalie_upserted,
    }


# ---------------------------------------------------------------------------
# Boxscore cross-reference helpers
# ---------------------------------------------------------------------------


def _build_boxscore_lookup(session: Session, game_id: int) -> dict[str, dict]:
    """Build a player_external_ref → stats dict from boxscore JSONB.

    Returns a dict keyed by player_external_ref with TOI, assists, etc.
    """
    rows = (
        session.query(db_models.SportsPlayerBoxscore)
        .filter(db_models.SportsPlayerBoxscore.game_id == game_id)
        .all()
    )
    lookup: dict[str, dict] = {}
    for row in rows:
        ref = row.player_external_ref
        stats = row.stats or {}

        # Parse TOI — may be stored as float minutes or "MM:SS" string
        toi = _parse_toi(stats)

        lookup[ref] = {
            "toi_minutes": toi,
            "assists": int(stats.get("assists", 0) or 0),
            "points": int(stats.get("points", 0) or 0),
            "blocked_shots": int(stats.get("blocked_shots", 0) or 0),
            "hits": int(stats.get("hits", 0) or 0),
            "position": stats.get("position", ""),
        }
    return lookup


def _parse_toi(stats: dict) -> float | None:
    """Extract TOI in decimal minutes from boxscore stats dict.

    Handles both float format (``"minutes": 18.45``) and string
    format (``"time_on_ice": "18:27"``).
    """
    # Try numeric minutes first
    minutes = stats.get("minutes")
    if minutes is not None:
        try:
            val = float(minutes)
            if val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass

    # Try MM:SS string format
    toi_str = stats.get("time_on_ice", "")
    if toi_str and ":" in str(toi_str):
        try:
            parts = str(toi_str).split(":")
            mins = int(parts[0])
            secs = int(parts[1])
            return round(mins + secs / 60, 2)
        except (ValueError, IndexError):
            pass

    return None


def _per_60(stat: int | None, toi_minutes: float | None) -> float | None:
    """Compute per-60-minute rate. Returns None if TOI unavailable."""
    if stat is None or toi_minutes is None or toi_minutes <= 0:
        return None
    return round((stat / toi_minutes) * 60, 2)


def _compute_game_score(
    goals: int | None,
    assists: int | None,
    shots: int | None,
    blocked_shots: int | None,
) -> float | None:
    """Simplified DOM game score formula for NHL skaters.

    game_score = G*0.75 + A*0.7 + SOG*0.075 + BLK*0.05
    """
    g = goals or 0
    a = assists or 0
    s = shots or 0
    blk = blocked_shots or 0

    if g == 0 and a == 0 and s == 0:
        return None

    return round(g * 0.75 + a * 0.7 + s * 0.075 + blk * 0.05, 2)
