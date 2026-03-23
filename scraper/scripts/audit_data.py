#!/usr/bin/env python3
"""Audit sports data quality and optionally fix obvious problems.

Usage:
    python scripts/audit_data.py                       # audit only
    python scripts/audit_data.py --league NFL          # single league
    python scripts/audit_data.py --fix                 # auto-fix obvious issues
    python scripts/audit_data.py --clear-caches        # clear caches (except odds)
    python scripts/audit_data.py --fix --clear-caches  # both
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, delete, exists, func, not_, text

script_dir = Path(__file__).resolve().parent
scraper_dir = script_dir.parent
sys.path.insert(0, str(scraper_dir))

api_dir = scraper_dir.parent / "api"
if str(api_dir) not in sys.path:
    sys.path.append(str(api_dir))

from sports_scraper.db import db_models, get_session  # noqa: E402

SportsGame = db_models.SportsGame
SportsLeague = db_models.SportsLeague
SportsTeam = db_models.SportsTeam
SportsTeamBoxscore = db_models.SportsTeamBoxscore
SportsPlayerBoxscore = db_models.SportsPlayerBoxscore
SportsGamePlay = db_models.SportsGamePlay
GameStatus = db_models.GameStatus

LEAGUES = ["NBA", "NHL", "MLB", "NCAAB", "NFL"]

# External ID key expected per league
EXTERNAL_ID_KEYS = {
    "NBA": "nba_game_id",
    "NHL": "nhl_game_pk",
    "MLB": "mlb_game_pk",
    "NCAAB": "cbb_game_id",
    "NFL": "espn_game_id",
}


# ---------------------------------------------------------------------------
# Audit functions — each returns (count, sample_ids, detail)
# ---------------------------------------------------------------------------


def _league_filter(query, league_code: str | None):
    """Add league filter to a query that joins SportsLeague."""
    if league_code:
        return query.filter(SportsLeague.code == league_code)
    return query


def _base_final_query(session, league_code: str | None):
    """Base query: final/archived games joined with league."""
    q = (
        session.query(SportsGame)
        .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
        .filter(SportsGame.status.in_([GameStatus.final.value, GameStatus.archived.value]))
    )
    return _league_filter(q, league_code)


def audit_missing_boxscores(session, league_code: str | None = None):
    """Final games with no team boxscore rows."""
    has_box = exists().where(SportsTeamBoxscore.game_id == SportsGame.id)
    q = _base_final_query(session, league_code).filter(not_(has_box))
    games = q.all()
    return {
        "count": len(games),
        "sample_ids": [g.id for g in games[:10]],
        "by_league": _count_by_league(session, [g.id for g in games]),
    }


def audit_missing_player_stats(session, league_code: str | None = None):
    """Final games with no player boxscore rows."""
    has_player = exists().where(SportsPlayerBoxscore.game_id == SportsGame.id)
    q = _base_final_query(session, league_code).filter(not_(has_player))
    games = q.all()
    return {
        "count": len(games),
        "sample_ids": [g.id for g in games[:10]],
        "by_league": _count_by_league(session, [g.id for g in games]),
    }


def audit_missing_pbp(session, league_code: str | None = None):
    """Final games with no play-by-play rows."""
    has_pbp = exists().where(SportsGamePlay.game_id == SportsGame.id)
    q = _base_final_query(session, league_code).filter(not_(has_pbp))
    games = q.all()
    return {
        "count": len(games),
        "sample_ids": [g.id for g in games[:10]],
        "by_league": _count_by_league(session, [g.id for g in games]),
    }


def audit_zero_scores(session, league_code: str | None = None):
    """Final games where both home and away score are 0 or NULL."""
    q = _base_final_query(session, league_code).filter(
        ((SportsGame.home_score == 0) | (SportsGame.home_score.is_(None)))
        & ((SportsGame.away_score == 0) | (SportsGame.away_score.is_(None)))
    )
    games = q.all()
    return {
        "count": len(games),
        "sample_ids": [g.id for g in games[:10]],
        "by_league": _count_by_league(session, [g.id for g in games]),
    }


def audit_stuck_games(session, league_code: str | None = None):
    """Games stuck in scheduled/pregame but game_date is >6 hours ago."""
    cutoff = datetime.now(UTC) - timedelta(hours=6)
    q = (
        session.query(SportsGame)
        .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
        .filter(
            SportsGame.status.in_([GameStatus.scheduled.value, GameStatus.pregame.value]),
            SportsGame.game_date < cutoff,
        )
    )
    q = _league_filter(q, league_code)
    games = q.all()
    return {
        "count": len(games),
        "sample_ids": [g.id for g in games[:10]],
        "by_league": _count_by_league(session, [g.id for g in games]),
    }


def audit_missing_external_ids(session, league_code: str | None = None):
    """Final games missing league-specific external ID."""
    results = {}
    leagues_to_check = [league_code] if league_code else LEAGUES
    for lc in leagues_to_check:
        key = EXTERNAL_ID_KEYS.get(lc)
        if not key:
            continue
        q = (
            _base_final_query(session, lc)
            .filter(
                (SportsGame.external_ids.is_(None))
                | (~SportsGame.external_ids.has_key(key))  # noqa: W601
                | (SportsGame.external_ids[key].astext == "")
            )
        )
        count = q.count()
        results[lc] = count
    return {
        "count": sum(results.values()),
        "by_league": results,
    }


def audit_advanced_stats_coverage(session, league_code: str | None = None):
    """Final games missing advanced stats."""
    results = {}
    leagues_to_check = [league_code] if league_code else LEAGUES
    for lc in leagues_to_check:
        total = _base_final_query(session, lc).count()
        missing = (
            _base_final_query(session, lc)
            .filter(SportsGame.last_advanced_stats_at.is_(None))
            .count()
        )
        results[lc] = {"total": total, "missing": missing, "pct": round((total - missing) / total * 100, 1) if total else 0}
    return {"by_league": results}


def audit_duplicates(session, league_code: str | None = None):
    """Games that share (league, home_team, away_team, game_date_day)."""
    # Use raw SQL for the date truncation
    sql = text("""
        SELECT league_id, home_team_id, away_team_id,
               DATE(game_date AT TIME ZONE 'US/Eastern') AS game_day,
               COUNT(*) AS cnt,
               ARRAY_AGG(id ORDER BY id) AS game_ids
        FROM sports_games
        GROUP BY league_id, home_team_id, away_team_id, game_day
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 50
    """)
    rows = session.execute(sql).fetchall()
    total_dupes = sum(r.cnt - 1 for r in rows)  # extra copies
    return {
        "count": total_dupes,
        "groups": len(rows),
        "samples": [{"game_ids": list(r.game_ids), "count": r.cnt} for r in rows[:5]],
    }


def _count_by_league(session, game_ids: list[int]) -> dict[str, int]:
    """Count game IDs by league code."""
    if not game_ids:
        return {}
    rows = (
        session.query(SportsLeague.code, func.count())
        .join(SportsGame, SportsGame.league_id == SportsLeague.id)
        .filter(SportsGame.id.in_(game_ids))
        .group_by(SportsLeague.code)
        .all()
    )
    return {code: count for code, count in rows}


# ---------------------------------------------------------------------------
# Fix functions
# ---------------------------------------------------------------------------


def fix_empty_stub_games(session, league_code: str | None = None):
    """Delete final games with 0/NULL scores AND no boxscores AND no PBP."""
    has_box = exists().where(SportsTeamBoxscore.game_id == SportsGame.id)
    has_pbp = exists().where(SportsGamePlay.game_id == SportsGame.id)

    q = (
        _base_final_query(session, league_code)
        .filter(
            ((SportsGame.home_score == 0) | (SportsGame.home_score.is_(None)))
            & ((SportsGame.away_score == 0) | (SportsGame.away_score.is_(None))),
            not_(has_box),
            not_(has_pbp),
        )
    )
    games = q.all()
    if not games:
        return 0

    game_ids = [g.id for g in games]
    # Delete related records first (odds, flows, etc.)
    for table in [
        db_models.SportsGameOdds,
        db_models.SportsPlayerBoxscore,
        db_models.SportsTeamBoxscore,
        db_models.SportsGamePlay,
    ]:
        session.execute(delete(table).where(table.game_id.in_(game_ids)))

    # Check for flow/timeline tables
    try:
        session.execute(delete(db_models.SportsGameFlow).where(db_models.SportsGameFlow.game_id.in_(game_ids)))
    except Exception:
        pass
    try:
        session.execute(delete(db_models.SportsGameTimelineArtifact).where(db_models.SportsGameTimelineArtifact.game_id.in_(game_ids)))
    except Exception:
        pass

    session.execute(delete(SportsGame).where(SportsGame.id.in_(game_ids)))
    session.commit()
    return len(game_ids)


def fix_stuck_games(session, league_code: str | None = None):
    """Mark games stuck in scheduled/pregame for >48h as canceled."""
    cutoff = datetime.now(UTC) - timedelta(hours=48)
    q = (
        session.query(SportsGame)
        .join(SportsLeague, SportsGame.league_id == SportsLeague.id)
        .filter(
            SportsGame.status.in_([GameStatus.scheduled.value, GameStatus.pregame.value]),
            SportsGame.game_date < cutoff,
        )
    )
    q = _league_filter(q, league_code)
    games = q.all()
    for g in games:
        g.status = GameStatus.canceled.value
        g.updated_at = datetime.now(UTC)
    session.commit()
    return len(games)


# ---------------------------------------------------------------------------
# Cache clearing
# ---------------------------------------------------------------------------


def clear_non_odds_caches():
    """Clear all caches except odds."""
    from sports_scraper.config import settings
    from sports_scraper.utils.cache import APICache, HTMLCache

    cleared = {}

    # HTML caches per league
    for league in LEAGUES:
        try:
            cache = HTMLCache(cache_dir=settings.scraper_config.html_cache_dir, league=league)
            result = cache.clear_recent_scoreboards(days=365)
            cleared[f"html_{league}"] = result.get("deleted_count", 0)
        except Exception as e:
            cleared[f"html_{league}"] = f"error: {e}"

    # API caches — clear all except odds-related
    api_names_to_clear = [
        "nhl_advanced", "nba_advanced", "mlb_advanced",
        "nfl_advanced", "ncaab_advanced",
        "nhl_pbp", "nba_pbp", "mlb_pbp", "ncaab_pbp", "nfl_pbp",
        "nhl_boxscore", "nba_boxscore", "mlb_boxscore",
        "ncaab_boxscore", "nfl_boxscore",
        "nhl_schedule", "nba_schedule", "mlb_schedule",
        "ncaab_schedule", "nfl_schedule",
        "nflverse_pbp",
    ]
    for api_name in api_names_to_clear:
        try:
            cache = APICache(cache_dir=settings.scraper_config.html_cache_dir, api_name=api_name)
            result = cache.clear()
            cleared[f"api_{api_name}"] = result.get("deleted_count", 0)
        except Exception as e:
            cleared[f"api_{api_name}"] = f"error: {e}"

    return cleared


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def print_summary(results: dict):
    """Print a formatted summary table."""
    print("\n" + "=" * 70)
    print("DATA QUALITY AUDIT")
    print("=" * 70)

    for check_name, data in results.items():
        print(f"\n--- {check_name.replace('_', ' ').title()} ---")
        if "count" in data:
            print(f"  Issues found: {data['count']}")
        if "by_league" in data:
            for lc, val in data["by_league"].items():
                if isinstance(val, dict):
                    print(f"  {lc}: {val.get('missing', 0)}/{val.get('total', 0)} missing ({val.get('pct', 0)}% covered)")
                elif val > 0:
                    print(f"  {lc}: {val}")
        if "groups" in data:
            print(f"  Duplicate groups: {data['groups']}")
        if "samples" in data:
            for s in data["samples"][:3]:
                print(f"    IDs: {s['game_ids'][:5]}... (x{s['count']})")
        if "sample_ids" in data and data.get("count", 0) > 0:
            print(f"  Sample IDs: {data['sample_ids'][:5]}")

    print("\n" + "=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Audit sports data quality")
    parser.add_argument("--league", type=str, help="Filter to specific league code")
    parser.add_argument("--fix", action="store_true", help="Auto-fix obvious issues (empty stubs, stuck games)")
    parser.add_argument("--clear-caches", action="store_true", help="Clear all caches except odds")
    args = parser.parse_args()

    league = args.league.upper() if args.league else None

    with get_session() as session:
        results = {}
        results["missing_boxscores"] = audit_missing_boxscores(session, league)
        results["missing_player_stats"] = audit_missing_player_stats(session, league)
        results["missing_pbp"] = audit_missing_pbp(session, league)
        results["zero_scores"] = audit_zero_scores(session, league)
        results["stuck_games"] = audit_stuck_games(session, league)
        results["missing_external_ids"] = audit_missing_external_ids(session, league)
        results["advanced_stats_coverage"] = audit_advanced_stats_coverage(session, league)
        results["duplicates"] = audit_duplicates(session, league)

        print_summary(results)

        if args.fix:
            print("\n--- FIXES ---")
            deleted = fix_empty_stub_games(session, league)
            print(f"  Deleted {deleted} empty stub games (final, 0 score, no data)")
            fixed = fix_stuck_games(session, league)
            print(f"  Marked {fixed} stuck games as canceled (scheduled/pregame >48h ago)")

    if args.clear_caches:
        print("\n--- CACHE CLEARING ---")
        cleared = clear_non_odds_caches()
        for name, count in cleared.items():
            if count and count != 0:
                print(f"  {name}: {count}")
        print("  (odds caches preserved)")

    print("\nDone.")


if __name__ == "__main__":
    main()
