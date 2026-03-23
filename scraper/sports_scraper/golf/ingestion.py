"""High-level golf data ingestion functions.

Each function creates a DataGolfClient, opens a DB session, fetches data
from the API, persists it, and returns a summary dict.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text

from ..db import get_session
from ..logging import logger
from .client import DataGolfClient
from .persistence import (
    upsert_dfs_projections,
    upsert_field,
    upsert_leaderboard,
    upsert_odds,
    upsert_player_stats,
    upsert_players,
    upsert_tournament,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_active_tournament(session: Any, tour: str = "pga") -> int | None:
    """Return the ``id`` of the currently active tournament for *tour*.

    An active tournament is one whose ``start_date <= today <= end_date``
    (or whose ``status`` is ``'in_progress'``).  Falls back to the next
    upcoming tournament if nothing is in-progress.
    """
    today = date.today()

    # First try: tournament in progress (date range or status)
    row = session.execute(
        text("""
            SELECT id FROM golf_tournaments
            WHERE tour = :tour
              AND (
                  status = 'in_progress'
                  OR (start_date <= :today AND (end_date >= :today OR end_date IS NULL))
              )
            ORDER BY start_date DESC
            LIMIT 1
        """),
        {"tour": tour, "today": today},
    ).fetchone()

    if row:
        return row[0]

    # Fallback: next upcoming tournament
    row = session.execute(
        text("""
            SELECT id FROM golf_tournaments
            WHERE tour = :tour AND start_date >= :today
            ORDER BY start_date ASC
            LIMIT 1
        """),
        {"tour": tour, "today": today},
    ).fetchone()

    return row[0] if row else None


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def sync_schedule(tour: str = "pga", season: int | None = None) -> dict:
    """Fetch the tour schedule from DataGolf and upsert tournaments."""
    client = DataGolfClient()
    tournaments = client.get_schedule(tour=tour, season=season)

    count = 0
    with get_session() as session:
        for t in tournaments:
            upsert_tournament(session, {
                "event_id": t.event_id,
                "tour": t.tour,
                "event_name": t.event_name,
                "course": t.course,
                "course_key": t.course_key,
                "start_date": t.start_date,
                "end_date": t.end_date,
                "season": t.season or (season),
                "purse": t.purse,
                "currency": t.currency,
                "country": t.country,
                "latitude": t.latitude,
                "longitude": t.longitude,
                "status": t.status,
            })
            count += 1

    summary = {"tour": tour, "tournaments_upserted": count}
    logger.info("golf_sync_schedule_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------

def sync_players() -> dict:
    """Fetch the full player list from DataGolf and upsert players."""
    client = DataGolfClient()
    players = client.get_player_list()

    player_dicts = [
        {
            "dg_id": p.dg_id,
            "player_name": p.player_name,
            "country": p.country,
            "country_code": p.country_code,
            "amateur": p.amateur,
            "dk_id": p.dk_id,
            "fd_id": p.fd_id,
            "yahoo_id": p.yahoo_id,
        }
        for p in players
    ]

    with get_session() as session:
        count = upsert_players(session, player_dicts)

    summary = {"players_upserted": count}
    logger.info("golf_sync_players_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Field
# ---------------------------------------------------------------------------

def sync_field(tour: str = "pga") -> dict:
    """Fetch field updates and upsert to the active tournament."""
    client = DataGolfClient()
    entries = client.get_field_updates(tour=tour)

    if not entries:
        logger.info("golf_sync_field_empty", tour=tour)
        return {"tour": tour, "field_entries_upserted": 0, "tournament_id": None}

    with get_session() as session:
        tournament_id = _find_active_tournament(session, tour=tour)
        if not tournament_id:
            logger.warning("golf_sync_field_no_active_tournament", tour=tour)
            return {"tour": tour, "field_entries_upserted": 0, "tournament_id": None}

        field_dicts = [
            {
                "dg_id": e.dg_id,
                "player_name": e.player_name,
                "tee_time_r1": e.r1_teetime or e.tee_time,
                "tee_time_r2": e.r2_teetime,
                "early_late": e.early_late,
                "course": e.course,
                "dk_salary": e.dk_salary,
                "fd_salary": e.fd_salary,
            }
            for e in entries
        ]

        count = upsert_field(session, tournament_id, field_dicts)

    summary = {"tour": tour, "field_entries_upserted": count, "tournament_id": tournament_id}
    logger.info("golf_sync_field_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------

def sync_leaderboard() -> dict:
    """Fetch in-play predictions and live stats, merge, and upsert leaderboard.

    Two DataGolf endpoints are combined:
    - ``/preds/in-play`` — positions, round scores (R1-R4), today, thru, probabilities
    - ``/preds/live-tournament-stats`` — strokes-gained metrics (SG total/OTT/APP/ARG/putt)

    They are merged by ``dg_id`` so the leaderboard has both scoring and SG data.
    """
    client = DataGolfClient()

    # Fetch both endpoints
    in_play = client.get_live_predictions()
    stats = client.get_live_tournament_stats()

    if not in_play and not stats:
        logger.info("golf_sync_leaderboard_empty")
        return {"leaderboard_entries_upserted": 0, "tournament_id": None}

    # Build lookup of SG stats by dg_id
    sg_by_id: dict[int, Any] = {}
    for e in stats:
        sg_by_id[e.dg_id] = e

    # Use in-play as the primary source (has positions, scores, probs).
    # Merge SG stats from the stats endpoint.
    primary = in_play if in_play else stats

    with get_session() as session:
        tournament_id = _find_active_tournament(session)
        if not tournament_id:
            logger.warning("golf_sync_leaderboard_no_active_tournament")
            return {"leaderboard_entries_upserted": 0, "tournament_id": None}

        lb_dicts = []
        for e in primary:
            sg = sg_by_id.get(e.dg_id)
            lb_dicts.append({
                "dg_id": e.dg_id,
                "player_name": e.player_name,
                "position": e.position,
                "total_score": e.total_score,
                "today_score": e.today_score,
                "thru": e.thru,
                "total_strokes": e.total_strokes,
                "r1": e.r1,
                "r2": e.r2,
                "r3": e.r3,
                "r4": e.r4,
                "status": e.status,
                "sg_total": (sg.sg_total if sg else None) or e.sg_total,
                "sg_ott": (sg.sg_ott if sg else None) or e.sg_ott,
                "sg_app": (sg.sg_app if sg else None) or e.sg_app,
                "sg_arg": (sg.sg_arg if sg else None) or e.sg_arg,
                "sg_putt": (sg.sg_putt if sg else None) or e.sg_putt,
                "win_prob": e.win_prob,
                "top_5_prob": e.top_5_prob,
                "top_10_prob": e.top_10_prob,
                "make_cut_prob": e.make_cut_prob,
            })

        count = upsert_leaderboard(session, tournament_id, lb_dicts)

    summary = {"leaderboard_entries_upserted": count, "tournament_id": tournament_id}
    logger.info("golf_sync_leaderboard_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------

def sync_odds(tour: str = "pga", market: str = "win") -> dict:
    """Fetch outright odds and upsert to the active tournament."""
    client = DataGolfClient()
    odds_entries = client.get_outrights(tour=tour, market=market)

    if not odds_entries:
        logger.info("golf_sync_odds_empty", tour=tour, market=market)
        return {"tour": tour, "market": market, "odds_upserted": 0, "tournament_id": None}

    with get_session() as session:
        tournament_id = _find_active_tournament(session, tour=tour)
        if not tournament_id:
            logger.warning("golf_sync_odds_no_active_tournament", tour=tour, market=market)
            return {"tour": tour, "market": market, "odds_upserted": 0, "tournament_id": None}

        odds_dicts = [
            {
                "dg_id": o.dg_id,
                "player_name": o.player_name,
                "book": o.book,
                "market": o.market,
                "odds": o.odds,
                "implied_prob": o.implied_prob,
                "dg_prob": o.dg_prob,
            }
            for o in odds_entries
        ]

        count = upsert_odds(session, tournament_id, odds_dicts)

    summary = {"tour": tour, "market": market, "odds_upserted": count, "tournament_id": tournament_id}
    logger.info("golf_sync_odds_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# DFS projections
# ---------------------------------------------------------------------------

def sync_dfs_projections(site: str = "draftkings", tour: str = "pga") -> dict:
    """Fetch DFS projections and upsert to the active tournament."""
    client = DataGolfClient()
    projections = client.get_dfs_projections(site=site, tour=tour)

    if not projections:
        logger.info("golf_sync_dfs_empty", site=site, tour=tour)
        return {"site": site, "tour": tour, "projections_upserted": 0, "tournament_id": None}

    with get_session() as session:
        tournament_id = _find_active_tournament(session, tour=tour)
        if not tournament_id:
            logger.warning("golf_sync_dfs_no_active_tournament", site=site, tour=tour)
            return {"site": site, "tour": tour, "projections_upserted": 0, "tournament_id": None}

        proj_dicts = [
            {
                "dg_id": p.dg_id,
                "player_name": p.player_name,
                "site": p.site,
                "salary": p.salary,
                "projected_points": p.projected_points,
                "projected_ownership": p.projected_ownership,
            }
            for p in projections
        ]

        count = upsert_dfs_projections(session, tournament_id, proj_dicts)

    summary = {"site": site, "tour": tour, "projections_upserted": count, "tournament_id": tournament_id}
    logger.info("golf_sync_dfs_complete", **summary)
    return summary


# ---------------------------------------------------------------------------
# Player stats (skill ratings)
# ---------------------------------------------------------------------------

def sync_stats(tour: str = "pga") -> dict:
    """Fetch skill ratings from DataGolf and upsert player stats."""
    client = DataGolfClient()
    ratings = client.get_skill_ratings(tour=tour)

    if not ratings:
        logger.info("golf_sync_stats_empty", tour=tour)
        return {"tour": tour, "stats_upserted": 0}

    stats_dicts = [
        {
            "dg_id": r.dg_id,
            "period": "current",
            "sg_total": r.sg_total,
            "sg_ott": r.sg_ott,
            "sg_app": r.sg_app,
            "sg_arg": r.sg_arg,
            "sg_putt": r.sg_putt,
            "driving_dist": r.driving_dist,
            "driving_acc": r.driving_acc,
            "sample_size": r.sample_size,
        }
        for r in ratings
    ]

    with get_session() as session:
        count = upsert_player_stats(session, stats_dicts)

    summary = {"tour": tour, "stats_upserted": count}
    logger.info("golf_sync_stats_complete", **summary)
    return summary
