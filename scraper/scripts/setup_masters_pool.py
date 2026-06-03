#!/usr/bin/env python3
"""Set up the RVCC Masters 2026 pool with the official field.

This script:
1. Ensures The Masters tournament exists in the DB
2. Maps the official field list to DataGolf player IDs
3. Creates golf_players entries for unmatched players (amateurs, etc.)
4. Inserts the full field into golf_tournament_fields
5. Creates the RVCC pool record
6. Sets the pool to 'open' so the frontend can accept entries

When DataGolf later publishes their field via sync_field, their entries
upsert by (tournament_id, dg_id). Players we created with synthetic IDs
stay alongside; players DataGolf knows get real leaderboard data.

Usage:
    python scripts/setup_masters_pool.py              # full setup (draft)
    python scripts/setup_masters_pool.py --open       # setup + open for entries
    python scripts/setup_masters_pool.py --field-only # just show field mapping
    python scripts/setup_masters_pool.py --dry-run    # preview without DB writes
    python scripts/setup_masters_pool.py --other "Luke Donald, Zach Blair"  # add extra players
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

script_dir = Path(__file__).resolve().parent
scraper_dir = script_dir.parent
sys.path.insert(0, str(scraper_dir))

api_dir = scraper_dir.parent / "api"
if str(api_dir) not in sys.path:
    sys.path.append(str(api_dir))

from setup_masters_data import (
    _SYNTHETIC_DG_ID_START,
    CLUB_CODE,
    ENTRY_DEADLINE,
    ENTRY_OPEN_AT,
    MASTERS_AMATEURS_2026,
    MASTERS_COURSE,
    MASTERS_END,
    MASTERS_EVENT_NAME,
    MASTERS_FIELD_2026,
    MASTERS_START,
    POOL_CODE,
    POOL_NAME,
    RVCC_RULES_JSON,
)
from setup_masters_matching import (
    create_unmatched_players,
    load_all_players,
    match_field_to_players,
)

from sports_scraper.db import get_session  # noqa: E402


def find_or_create_masters_tournament(session, *, dry_run: bool = False) -> int:
    """Find The Masters 2026 or create it. Returns tournament id."""
    # Try to find existing
    row = session.execute(
        text("""
            SELECT id, event_name, start_date, status
            FROM golf_tournaments
            WHERE (LOWER(event_name) LIKE '%masters%' OR LOWER(event_name) LIKE '%augusta%')
              AND start_date >= '2026-04-01' AND start_date <= '2026-04-15'
            ORDER BY start_date
            LIMIT 1
        """)
    ).fetchone()

    if row:
        print(f"  Found existing tournament: {row[1]} (id={row[0]}, status={row[3]})")
        return row[0]

    # Also try by event_id if DataGolf has synced it with a different name
    row = session.execute(
        text("""
            SELECT id, event_name, start_date, status
            FROM golf_tournaments
            WHERE tour = 'pga'
              AND start_date >= '2026-04-01' AND start_date <= '2026-04-15'
            ORDER BY start_date
            LIMIT 1
        """)
    ).fetchone()

    if row:
        print(f"  Found tournament by date: {row[1]} (id={row[0]}, status={row[3]})")
        return row[0]

    if dry_run:
        print("  [DRY RUN] Would create The Masters tournament")
        return -1

    # Create it
    result = session.execute(
        text("""
            INSERT INTO golf_tournaments
                (event_id, tour, event_name, course, course_key,
                 start_date, end_date, season, status, created_at, updated_at)
            VALUES
                (:event_id, 'pga', :event_name, :course, :course_key,
                 :start_date, :end_date, 2026, 'scheduled', NOW(), NOW())
            ON CONFLICT ON CONSTRAINT uq_golf_tournament_event_tour DO UPDATE SET
                event_name = EXCLUDED.event_name,
                course = EXCLUDED.course,
                start_date = EXCLUDED.start_date,
                end_date = EXCLUDED.end_date,
                updated_at = NOW()
            RETURNING id
        """),
        {
            "event_id": "014",  # DataGolf Masters event_id
            "event_name": MASTERS_EVENT_NAME,
            "course": MASTERS_COURSE,
            "course_key": "augusta_national",
            "start_date": MASTERS_START,
            "end_date": MASTERS_END,
        },
    )
    tid = result.fetchone()[0]
    session.commit()
    print(f"  Created tournament: {MASTERS_EVENT_NAME} (id={tid})")
    return tid


def insert_field(session, tournament_id: int, matched: list[dict], *, dry_run: bool = False) -> int:
    """Insert matched players into golf_tournament_fields."""
    if dry_run:
        print(f"  [DRY RUN] Would insert {len(matched)} field entries")
        return 0

    sql = text("""
        INSERT INTO golf_tournament_fields
            (tournament_id, dg_id, player_name, status, updated_at)
        VALUES
            (:tournament_id, :dg_id, :player_name, 'active', NOW())
        ON CONFLICT ON CONSTRAINT uq_golf_field_entry DO UPDATE SET
            player_name = EXCLUDED.player_name,
            status = EXCLUDED.status,
            updated_at = NOW()
    """)

    count = 0
    for m in matched:
        session.execute(sql, {
            "tournament_id": tournament_id,
            "dg_id": m["dg_id"],
            "player_name": m["dg_name"],
        })
        count += 1

    session.commit()
    return count


def create_pool(session, tournament_id: int, *, status: str = "draft", dry_run: bool = False) -> int:
    """Create the RVCC Masters pool. Returns pool id."""
    # Check for existing
    row = session.execute(
        text("""
            SELECT id, status FROM golf_pools
            WHERE tournament_id = :tid AND club_code = :club
            LIMIT 1
        """),
        {"tid": tournament_id, "club": CLUB_CODE},
    ).fetchone()

    if row:
        print(f"  Pool already exists (id={row[0]}, status={row[1]})")
        return row[0]

    if dry_run:
        print(f"  [DRY RUN] Would create pool '{POOL_NAME}' with status='{status}'")
        return -1

    result = session.execute(
        text("""
            INSERT INTO golf_pools
                (code, name, club_code, tournament_id, status, rules_json,
                 entry_open_at, entry_deadline, max_entries_per_email,
                 scoring_enabled, require_upload, allow_self_service_entry,
                 notes, created_at, updated_at)
            VALUES
                (:code, :name, :club_code, :tournament_id, :status,
                 CAST(:rules_json AS jsonb),
                 CAST(:entry_open_at AS timestamptz), CAST(:entry_deadline AS timestamptz),
                 :max_entries_per_email,
                 FALSE, FALSE, TRUE,
                 :notes, NOW(), NOW())
            RETURNING id
        """),
        {
            "code": POOL_CODE,
            "name": POOL_NAME,
            "club_code": CLUB_CODE,
            "tournament_id": tournament_id,
            "status": status,
            "rules_json": json.dumps(RVCC_RULES_JSON),
            "entry_open_at": ENTRY_OPEN_AT,
            "entry_deadline": ENTRY_DEADLINE,
            "max_entries_per_email": 3,
            "notes": (
                "RVCC Masters Pool 2026. "
                "Pick 7 golfers, best 5 scores count. "
                "Min 5 must make the cut to qualify. "
                "Lowest aggregate wins."
            ),
        },
    )
    pool_id = result.fetchone()[0]
    session.commit()
    return pool_id


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Set up RVCC Masters 2026 pool")
    parser.add_argument("--open", action="store_true", help="Set pool to 'open' (accepting entries)")
    parser.add_argument("--field-only", action="store_true", help="Just show field mapping results")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to DB")
    parser.add_argument(
        "--other",
        type=str,
        default="",
        help="Comma-separated extra player names to add (e.g. --other 'Luke Donald, Zach Blair')",
    )
    args = parser.parse_args()

    # Build full field: hardcoded list + amateurs + --other additions
    all_field = list(MASTERS_FIELD_2026)
    for n in MASTERS_AMATEURS_2026:
        if n not in all_field:
            all_field.append(n)

    if args.other:
        for name in args.other.split(","):
            name = name.strip()
            if name and name not in all_field:
                all_field.append(name)
                print(f"  Added via --other: {name}")

    # Step 1: Load player catalog and match names
    print("\n[1] Matching field to DataGolf player IDs...")
    with get_session() as session:
        player_index = load_all_players(session)

    print(f"  Loaded {len(player_index)} player name variants from golf_players")
    matched, unmatched = match_field_to_players(all_field, player_index)
    print(f"  Matched: {len(matched)} / {len(all_field)}")

    # Step 2: Create golf_players entries for unmatched (amateurs, --other, etc.)
    newly_created: list[dict] = []
    if unmatched:
        print(f"\n[2] Creating {len(unmatched)} unmatched players with synthetic dg_ids...")
        for name in unmatched:
            tag = " (A)" if name in MASTERS_AMATEURS_2026 else ""
            print(f"    + {name}{tag}")
        with get_session() as session:
            newly_created = create_unmatched_players(session, unmatched, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"  Created {len(newly_created)} player entries (dg_id {_SYNTHETIC_DG_ID_START}+)")
    else:
        print("\n[2] All players matched — no synthetic entries needed")

    # Combine matched + newly created for the full field
    full_field = matched + newly_created

    # Print full field mapping
    print(f"\n  {'#':<4} {'Field Name':<35} {'DG Name':<30} {'DG ID':<8} {'Source':<10}")
    print(f"  {'-'*4} {'-'*35} {'-'*30} {'-'*8} {'-'*10}")
    for i, m in enumerate(sorted(full_field, key=lambda x: x["field_name"]), 1):
        amateur = " (A)" if m.get("amateur") else ""
        source = "synthetic" if m["dg_id"] >= _SYNTHETIC_DG_ID_START else "datagolf"
        print(f"  {i:<4} {m['field_name'] + amateur:<35} {m['dg_name']:<30} {m['dg_id']:<8} {source:<10}")

    print(f"\n  Total field: {len(full_field)} players")

    if args.field_only:
        return

    # Step 3: Find or create The Masters tournament
    print("\n[3] Finding/creating The Masters 2026 tournament...")
    with get_session() as session:
        tournament_id = find_or_create_masters_tournament(session, dry_run=args.dry_run)

    if tournament_id < 0:
        return

    # Step 4: Insert full field (matched + newly created)
    print(f"\n[4] Inserting {len(full_field)} players into tournament field...")
    with get_session() as session:
        count = insert_field(session, tournament_id, full_field, dry_run=args.dry_run)
    if not args.dry_run:
        print(f"  Upserted {count} field entries")

    # Step 5: Create pool
    initial_status = "open" if args.open else "draft"
    print(f"\n[5] Creating RVCC pool (status='{initial_status}')...")
    with get_session() as session:
        pool_id = create_pool(session, tournament_id, status=initial_status, dry_run=args.dry_run)

    if pool_id < 0:
        return

    # If --open and pool already existed, update status
    if args.open and not args.dry_run:
        with get_session() as session:
            session.execute(
                text("""
                    UPDATE golf_pools SET status = 'open', updated_at = NOW()
                    WHERE id = :id AND status != 'open'
                """),
                {"id": pool_id},
            )
            session.commit()

    # Summary
    dg_count = len([m for m in full_field if m["dg_id"] < _SYNTHETIC_DG_ID_START])
    syn_count = len([m for m in full_field if m["dg_id"] >= _SYNTHETIC_DG_ID_START])

    print(f"\n{'='*60}")
    print(" RVCC Masters Pool 2026 - Setup Complete")
    print(f"{'='*60}")
    print(f"  Tournament ID:    {tournament_id}")
    print(f"  Pool ID:          {pool_id}")
    print(f"  Field size:       {len(full_field)} players")
    print(f"    DataGolf-matched: {dg_count}")
    print(f"    Synthetic IDs:    {syn_count} (amateurs / --other)")
    print("  Entry opens:      April 1, 2026")
    print("  Entry deadline:   April 9, 2026 at 8:00 AM ET")
    print(f"  Status:           {initial_status}")
    print()
    print("  RVCC Rules:")
    print("    - Pick any 7 golfers from the field")
    print("    - At least 5 must make the cut to qualify")
    print("    - Best 5 scores count toward your total")
    print("    - If 6-7 make the cut, worst 1-2 are dropped")
    print("    - Lowest aggregate score wins")
    print()
    print("  Lifecycle (auto-managed):")
    print("    Now         -> status='open', entries accepted")
    print("    Apr 9 8a ET -> auto-locked (entry_deadline passed)")
    print("    Apr 9 2p ET -> auto-activated (scoring_starts_at in rules_json)")
    print("                   status='live', scoring_enabled=true")
    print(f"    Apr 12      -> PATCH /api/golf/pools/{pool_id} {{status: 'final'}}")
    print()
    print("  Frontend endpoints:")
    print(f"    GET  /api/golf/pools/{pool_id}/field          -- pick from these players")
    print(f"    POST /api/golf/pools/{pool_id}/entries        -- submit 7 picks")
    print(f"    GET  /api/golf/pools/{pool_id}/leaderboard    -- live standings")
    print(f"    GET  /api/golf/pools/{pool_id}/entries/by-email?email=x -- lookup picks")
    print()
    print("  DataGolf reconciliation:")
    print("    When DataGolf publishes the Masters field, sync_field will add")
    print("    entries by real dg_id alongside synthetic ones. Players with")
    print("    real dg_ids get live leaderboard scoring automatically.")
    print("    Synthetic-ID players show as 'unknown' until reconciled.")
    print()
    print("  Auto-running (Celery beat, already configured):")
    print("    - Field sync:       every 6 hours (will pick up DG field)")
    print("    - Leaderboard sync: every 5 min (DataGolf)")
    print("    - Pool scoring:     every 5 min (when status='live')")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
