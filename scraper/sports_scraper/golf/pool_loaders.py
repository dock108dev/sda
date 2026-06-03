"""Golf pool scoring database readers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _load_live_pools(session: Session) -> list[dict[str, Any]]:
    """Load all pools with status='live' and scoring_enabled=True."""
    rows = session.execute(
        text("""
            SELECT id, club_code, tournament_id, rules_json, status
            FROM golf_pools
            WHERE status = 'live' AND scoring_enabled = TRUE
        """)
    ).fetchall()

    return [
        {
            "id": r[0],
            "club_code": r[1],
            "tournament_id": r[2],
            "rules_json": r[3],
            "status": r[4],
        }
        for r in rows
    ]


def _load_entries_and_picks(session: Session, pool_id: int) -> list[dict[str, Any]]:
    """Load all entries and their picks for a pool."""
    entry_rows = session.execute(
        text("""
            SELECT id, email, entry_name
            FROM golf_pool_entries
            WHERE pool_id = :pool_id
        """),
        {"pool_id": pool_id},
    ).fetchall()

    entries = []
    for er in entry_rows:
        entry_id = er[0]
        pick_rows = session.execute(
            text("""
                SELECT dg_id, player_name_snapshot, pick_slot, bucket_number
                FROM golf_pool_entry_picks
                WHERE entry_id = :entry_id
                ORDER BY pick_slot
            """),
            {"entry_id": entry_id},
        ).fetchall()

        picks = [
            {
                "dg_id": pr[0],
                "player_name": pr[1],
                "pick_slot": pr[2],
                "bucket_number": pr[3],
            }
            for pr in pick_rows
        ]

        entries.append({
            "entry_id": entry_id,
            "email": er[1],
            "entry_name": er[2],
            "picks": picks,
        })

    return entries


def _load_leaderboard(session: Session, tournament_id: int) -> dict[int, dict[str, Any]]:
    """Load leaderboard data keyed by dg_id."""
    rows = session.execute(
        text("""
            SELECT dg_id, player_name, status, position, total_score,
                   thru, r1, r2, r3, r4
            FROM golf_leaderboard
            WHERE tournament_id = :tournament_id
        """),
        {"tournament_id": tournament_id},
    ).fetchall()

    return {
        r[0]: {
            "dg_id": r[0],
            "player_name": r[1],
            "status": r[2],
            "position": r[3],
            "total_score": r[4],
            "thru": r[5],
            "r1": r[6],
            "r2": r[7],
            "r3": r[8],
            "r4": r[9],
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# Pure scoring logic (lightweight port from api scoring engine)
# ---------------------------------------------------------------------------
