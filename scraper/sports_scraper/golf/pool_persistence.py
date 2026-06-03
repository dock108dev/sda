"""Golf pool materialized score writers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _upsert_entry_score(session: Session, pool_id: int, scored: dict[str, Any]) -> None:
    """Upsert a single materialized entry score row.

    Unique constraint: ``entry_id`` (not ``pool_id, entry_id``).
    """
    session.execute(
        text("""
            INSERT INTO golf_pool_entry_scores
                (pool_id, entry_id, rank, is_tied, aggregate_score,
                 qualified_golfers_count, counted_golfers_count,
                 qualification_status, is_complete, last_scored_at,
                 updated_at)
            VALUES
                (:pool_id, :entry_id, :rank, :is_tied, :aggregate_score,
                 :qualified_golfers_count, :counted_golfers_count,
                 :qualification_status, :is_complete, NOW(), NOW())
            ON CONFLICT (entry_id) DO UPDATE SET
                pool_id                 = EXCLUDED.pool_id,
                rank                    = EXCLUDED.rank,
                is_tied                 = EXCLUDED.is_tied,
                aggregate_score         = EXCLUDED.aggregate_score,
                qualified_golfers_count = EXCLUDED.qualified_golfers_count,
                counted_golfers_count   = EXCLUDED.counted_golfers_count,
                qualification_status    = EXCLUDED.qualification_status,
                is_complete             = EXCLUDED.is_complete,
                last_scored_at          = NOW(),
                updated_at              = NOW()
        """),
        {
            "pool_id": pool_id,
            "entry_id": scored["entry_id"],
            "rank": scored["rank"],
            "is_tied": scored["is_tied"],
            "aggregate_score": scored["aggregate_score"],
            "qualified_golfers_count": scored["qualified_golfers_count"],
            "counted_golfers_count": scored["counted_golfers_count"],
            "qualification_status": scored["qualification_status"],
            "is_complete": scored["is_complete"],
        },
    )


def _upsert_score_players(
    session: Session,
    pool_id: int,
    entry_id: int,
    picks: list[dict[str, Any]],
) -> None:
    """Upsert per-golfer score detail rows.

    Column names use ``_snapshot`` suffix where the migration defines them:
    ``player_name_snapshot``, ``status_snapshot``, ``position_snapshot``,
    ``thru_snapshot``, ``total_score_snapshot``, ``made_cut_snapshot``.
    Round columns ``r1``-``r4`` have no suffix.

    Unique constraint: ``(entry_id, dg_id)``
    """
    for pick in picks:
        session.execute(
            text("""
                INSERT INTO golf_pool_entry_score_players
                    (pool_id, entry_id, dg_id, player_name_snapshot, pick_slot,
                     bucket_number, status_snapshot, position_snapshot,
                     total_score_snapshot, thru_snapshot,
                     r1, r2, r3, r4,
                     made_cut_snapshot, counts_toward_total, is_dropped,
                     sort_score, last_scored_at, updated_at)
                VALUES
                    (:pool_id, :entry_id, :dg_id, :player_name, :pick_slot,
                     :bucket_number, :status, :position,
                     :total_score, :thru,
                     :r1, :r2, :r3, :r4,
                     :made_cut, :counts_toward_total, :is_dropped,
                     :sort_score, NOW(), NOW())
                ON CONFLICT (entry_id, dg_id) DO UPDATE SET
                    pool_id                 = EXCLUDED.pool_id,
                    player_name_snapshot    = EXCLUDED.player_name_snapshot,
                    pick_slot               = EXCLUDED.pick_slot,
                    bucket_number           = EXCLUDED.bucket_number,
                    status_snapshot         = EXCLUDED.status_snapshot,
                    position_snapshot       = EXCLUDED.position_snapshot,
                    total_score_snapshot    = EXCLUDED.total_score_snapshot,
                    thru_snapshot           = EXCLUDED.thru_snapshot,
                    r1                      = EXCLUDED.r1,
                    r2                      = EXCLUDED.r2,
                    r3                      = EXCLUDED.r3,
                    r4                      = EXCLUDED.r4,
                    made_cut_snapshot       = EXCLUDED.made_cut_snapshot,
                    counts_toward_total     = EXCLUDED.counts_toward_total,
                    is_dropped              = EXCLUDED.is_dropped,
                    sort_score              = EXCLUDED.sort_score,
                    last_scored_at          = NOW(),
                    updated_at              = NOW()
            """),
            {
                "pool_id": pool_id,
                "entry_id": entry_id,
                "dg_id": pick["dg_id"],
                "player_name": pick["player_name"],
                "pick_slot": pick["pick_slot"],
                "bucket_number": pick.get("bucket_number"),
                "status": pick["status"],
                "position": pick.get("position"),
                "total_score": pick.get("total_score"),
                "thru": pick.get("thru"),
                "r1": pick.get("r1"),
                "r2": pick.get("r2"),
                "r3": pick.get("r3"),
                "r4": pick.get("r4"),
                "made_cut": pick["made_cut"],
                "counts_toward_total": pick["counts_toward_total"],
                "is_dropped": pick["is_dropped"],
                "sort_score": pick.get("sort_score"),
            },
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
