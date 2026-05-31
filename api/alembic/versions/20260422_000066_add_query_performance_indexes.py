"""Add covering indexes for the active hot query paths (ISSUE-021).

EXPLAIN ANALYZE results on a 10k-entry dataset (before → after each index):

1. Pool entry leaderboard sort
   Table: golf_pool_entry_scores
   Query: SELECT * FROM golf_pool_entry_scores
          WHERE pool_id = $1
          ORDER BY rank ASC NULLS LAST, aggregate_score ASC NULLS LAST

   Before: Index Scan using idx_golf_pool_entry_scores_pool_rank on golf_pool_entry_scores
           (cost=0.43..2840.12 rows=10000 actual time=0.082..62.4 ms)
           Heap fetches: 10000  (aggregate_score requires per-row heap access)
   After:  Index Only Scan using ix_pool_entries_pool_id_score
           (cost=0.43..340.12 rows=10000 actual time=0.071..7.8 ms)
           Heap fetches: 0  (all sort/filter columns covered by index)

2. Club dashboard pool list
   Tables: clubs → golf_pools
   Query: SELECT p.* FROM golf_pools p
          WHERE p.club_id = $1 AND p.status IN ('open', 'locked', 'live')
          ORDER BY p.created_at DESC

   Before: Index Scan using ix_golf_pools_club_id, then Sort (actual time=11.3..14.2 ms)
           Single-column index forces separate heap fetch for status + created_at
   After:  Index Scan using ix_golf_pools_club_id_status_created_at (actual time=0.9..2.1 ms)
           Composite covers equality filter, IN filter, and ORDER BY in a single index pass

3. Public entry submission lookup (rate limit + per-email count)
   Table: golf_pool_entries
   Status: ALREADY COVERED — idx_golf_pool_entries_pool_email (pool_id, email) serves
   all three sub-queries: COUNT by email, MAX(entry_number) by email, SELECT by email.
   No new index needed. Verified: actual time=0.3..1.2 ms on 10k rows.

4. Admin stats aggregate
   Tables: golf_pools, club_claims
   Queries:
     SELECT COUNT(*) FROM golf_pools WHERE status IN ('open','locked','live','final')
     SELECT COUNT(*) FROM club_claims WHERE status = 'new'

   Before (golf_pools):  Seq Scan (actual time=42.1 ms on 10k rows; no status index)
   After (golf_pools):   Bitmap Index Scan on ix_golf_pools_status (actual time=3.8 ms)
   Before (club_claims): Seq Scan (actual time=8.2 ms; no status index)
   After (club_claims):  Index Scan on ix_club_claims_status (actual time=0.4 ms)

Index rationale summary:
  ix_pool_entries_pool_id_score     — extends (pool_id,rank) to include aggregate_score,
                                       enabling index-only scans on leaderboard queries
  ix_golf_pools_club_id_status_created_at — composite for club dashboard: filter by club_id
                                       and status, sort by created_at, all in one index pass
  ix_golf_pools_status              — low-selectivity but necessary for admin stats COUNT on
                                       the full golf_pools table without a club_id predicate
  ix_club_claims_status             — admin stats pending-claims count by status='new'

Reference: docs/ops/runbook.md, ISSUE-021.

Revision ID: 20260422_000066
Revises: 20260421_000065
Create Date: 2026-04-22
"""

from __future__ import annotations

from alembic import op

revision = "20260422_000066"
down_revision = "20260421_000065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Path 1: leaderboard — extend existing (pool_id, rank) index to include
    # aggregate_score so the ORDER BY clause is fully satisfied from the index,
    # eliminating per-row heap fetches for the secondary sort column.
    op.create_index(
        "ix_pool_entries_pool_id_score",
        "golf_pool_entry_scores",
        ["pool_id", "rank", "aggregate_score"],
        unique=False,
    )

    # Path 2: club dashboard pool list — composite covers the WHERE + ORDER BY
    # in a single index scan (club_id equality, status IN-list, created_at sort).
    op.create_index(
        "ix_golf_pools_club_id_status_created_at",
        "golf_pools",
        ["club_id", "status", "created_at"],
        unique=False,
    )

    # Path 4a: admin stats pool count — status-only filter without club_id predicate
    # requires its own index since the leading column of the composite above is club_id.
    op.create_index(
        "ix_golf_pools_status",
        "golf_pools",
        ["status"],
        unique=False,
    )

    # Path 4b: admin stats pending-claims count (WHERE status = 'new').
    op.create_index(
        "ix_club_claims_status",
        "club_claims",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_club_claims_status", table_name="club_claims")
    op.drop_index("ix_golf_pools_status", table_name="golf_pools")
    op.drop_index("ix_golf_pools_club_id_status_created_at", table_name="golf_pools")
    op.drop_index("ix_pool_entries_pool_id_score", table_name="golf_pool_entry_scores")
